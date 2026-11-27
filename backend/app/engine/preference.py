"""① 취향 추정: 시청 기록 + 첫날 정보(관심사) → 취향 점수표(0~1)와 시청 습관.

- 신호 세기: 직접 고름 1.0 / 이어짐·추천 0.3 / 5분 미만·취소 0
- 본 날 기준 반감기: 최근 본 날부터 세어 14번째 본 날의 기록은 절반 (달력 날짜가 아님 — 띄엄띄엄 보는 분도 공평)
- 기록이 적으면 첫날 정보(seed_prefs)를 더 믿음: 기록 비중 = n / (n + 10)
- 장르가 여러 개인 기록은 각 장르에 같은 무게로 더함 (나눠 갖지 않음)
- 하루 틀(시청 시간대·하루 총 시간)은 신호 세기와 상관없이 TV 켜짐 패턴으로 (tv_pattern.py)
- 장르별 실제 시청 비율은 직접 고른 시청으로
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from ..models.db import Senior, WatchLog
from . import config
from .genres import genres_of
from .tv_pattern import LOW, daily_on_minutes, on_ratio_by_hour, tier_of, usual_channel_by_hour


def band_of(dt: datetime) -> str:
    """시각 → 시간대 이름 (아침·낮·저녁·밤). 0~5시는 밤."""
    for name, start, end in config.TIME_BANDS:
        if start <= dt.hour < end:
            return name
    return "밤"


@dataclass(frozen=True)
class WeightedLog:
    log: WatchLog
    weight: float


@dataclass
class Profile:
    series: dict[str, float]
    cast: dict[str, float]
    genre: dict[str, float]
    timeslot: dict[str, float]  # 시간대 이름 → 0~1
    history_share: float  # 시청 기록을 믿는 비율 (0 = 첫날 정보만)
    n_logs: int
    daily_budget_min: float = config.DEFAULT_BUDGET_MIN  # 하루 총 시간 상한 (분) = 하루 TV 켜짐 시간 평균
    focus_budget_min: float | None = (
        None  # 집중 시청(pick) 상한 = 골라 본 시간 평균. None 이면 하루 총 시간과 같음
    )
    on_ratio: dict[int, float] = field(default_factory=dict)  # 시각(0~23) → TV 켜짐 비율. 비면 패턴 모름
    usual_channel: dict[int, str] = field(default_factory=dict)  # 시각 → 평소 켜 두는 채널
    left_on_series: set[str] = field(default_factory=set)  # '틀어만 놓기' 기록만 있는 시리즈 → 배경 편성 후보
    genre_watch_share: dict[str, float] = field(
        default_factory=dict
    )  # 대표 장르별 실제 시청 비율 (직접 고른 시청)
    genre_seen_share: dict[str, float] = field(
        default_factory=dict
    )  # 장르 목록 기준, 시청 시간 중 그 장르가 든 비율

    def timeslot_score(self, dt: datetime) -> float:
        return self.timeslot.get(band_of(dt), 0.0)

    def tier(self, hour: int) -> str:
        """그 시각의 TV 켜짐 단계 (높음·중간·낮음). 패턴을 모르면 '중간'."""
        return tier_of(self.on_ratio, hour)

    def viewing_hours(self) -> set[int]:
        """시청 시간대 = TV 켜짐 단계가 '중간' 이상인 시각들 (패턴을 모르면 0~23시 전부)."""
        return {h for h in range(24) if self.tier(h) != LOW}

    @property
    def pattern_known(self) -> bool:
        return bool(self.on_ratio)

    @property
    def knows_taste(self) -> bool:
        """관심사나 시청 기록에서 시리즈·출연자·장르 취향을 하나라도 알고 있나."""
        return any(v > 0 for d in (self.series, self.cast, self.genre) for v in d.values())

    def favorite_genre(self) -> str | None:
        """가장 좋아하는 장르 (같으면 이름순). 모르면 None."""
        liked = [(v, g) for g, v in self.genre.items() if v > 0]
        return min(liked, key=lambda vg: (-vg[0], vg[1]))[1] if liked else None


def weigh_logs(logs: list[WatchLog], today: date) -> list[WeightedLog]:
    """취향 계산에 쓸 기록과 그 무게. 버릴 기록(5분 미만·취소·60일 넘음·신호 0)은 빠진다."""
    kept = [
        lg
        for lg in logs
        if not lg.cancelled
        and lg.watched_min >= config.MIN_WATCH_MIN
        and 0 <= (today - lg.started_at.date()).days <= config.MAX_AGE_DAYS
        and config.SIGNAL.get(lg.how_started, 0) > 0
    ]
    viewing_days = sorted({lg.started_at.date() for lg in kept}, reverse=True)
    rank = {d: i for i, d in enumerate(viewing_days)}  # 0 = 가장 최근에 본 날
    # 반감기: 최근 본 날에서 14번째 본 날 전 기록은 무게 절반, 28번째는 1/4 ... (0.5 ^ (몇 번째 본 날 / 14))
    return [
        WeightedLog(
            lg,
            config.SIGNAL[lg.how_started] * 0.5 ** (rank[lg.started_at.date()] / config.HALF_LIFE_VIEW_DAYS),
        )
        for lg in kept
    ]


def _recent(logs: list[WatchLog], today: date, signals: tuple[str, ...]) -> list[WatchLog]:
    """최근 PATTERN_RECENT_DAYS 일 안의 유효 기록 중 how_started 가 signals 인 것."""
    return [
        w.log
        for w in weigh_logs(logs, today)
        if w.log.how_started in signals
        and (today - w.log.started_at.date()).days <= config.PATTERN_RECENT_DAYS
    ]


def focus_budget_min(logs: list[WatchLog], today: date) -> float | None:
    """집중 시청 상한 = 최근 14일 동안 직접 고르거나 추천으로 본(FOCUS_SIGNALS) 시간의 하루 평균 (그런 기록이 있는 날 기준).
    TV 켜짐 패턴을 모르면(기록 있는 날 < PATTERN_MIN_DAYS) None → 하루 총 시간을 그대로 씀."""
    if not on_ratio_by_hour(logs, today):
        return None
    minutes: dict[date, float] = defaultdict(float)
    for log in _recent(logs, today, config.FOCUS_SIGNALS):
        minutes[log.started_at.date()] += log.watched_min
    return sum(minutes.values()) / len(minutes) if minutes else 0.0


def daily_budget_min(logs: list[WatchLog], today: date) -> float:
    """하루 총 시간 상한 = 하루 TV 켜짐 시간 평균 (tv_pattern.daily_on_minutes, 모든 신호 100%)."""
    return daily_on_minutes(logs, today)


def genre_watch_share(logs: list[WatchLog], today: date) -> dict[str, float]:
    """대표 장르별 실제 시청 비율 (최근 직접 고른 시청 시간 기준). 기준표 S2 상한에 씀."""
    minutes: dict[str, float] = defaultdict(float)
    for log in _recent(logs, today, config.WATCH_SHARE_SIGNALS):
        minutes[log.genre] += log.watched_min
    total = sum(minutes.values())
    return {g: m / total for g, m in minutes.items()} if total else {}


def genre_seen_share(logs: list[WatchLog], today: date) -> dict[str, float]:
    """장르 목록 기준으로, 유효 시청 시간 중 그 장르가 들어 있던 비율. "거의 안 본 장르"(새로 추천) 판단에 씀."""
    kept = [w.log for w in weigh_logs(logs, today)]
    total = sum(log.watched_min for log in kept)
    minutes: dict[str, float] = defaultdict(float)
    for log in kept:
        for g in genres_of(log):
            minutes[g] += log.watched_min
    return {g: m / total for g, m in minutes.items()} if total else {}


def _normalize(d: dict[str, float]) -> dict[str, float]:
    top = max(d.values(), default=0.0)
    return {k: v / top for k, v in d.items()} if top > 0 else {}


def _blend(history: dict[str, float], seed: dict[str, float], share: float) -> dict[str, float]:
    keys = history.keys() | seed.keys()
    return {k: share * history.get(k, 0.0) + (1 - share) * seed.get(k, 0.0) for k in keys}


def _left_on_only(weighted: list[WeightedLog], seed: dict) -> set[str]:
    """'틀어만 놓기'(continued) 기록만 있고 직접 고르거나 추천으로 본 적이 없는 시리즈 (관심사로 고른 시리즈는 제외)."""
    hows: dict[str, set[str]] = defaultdict(set)
    for w in weighted:
        hows[w.log.series_key].add(w.log.how_started)
    return {k for k, h in hows.items() if h == {"continued"}} - set(seed.get("series") or [])


def build_profile(logs: list[WatchLog], senior: Senior, today: date) -> Profile:
    """시청 기록과 첫날 관심사(seed_prefs)를 섞어 취향표를 만든다. 관심사를 바꾸면 다음 계산에 바로 반영된다."""
    weighted = weigh_logs(logs, today)
    series, cast, genre, slot = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float)
    for w in weighted:
        series[w.log.series_key] += w.weight
        for g in genres_of(w.log):
            genre[g] += w.weight
        slot[band_of(w.log.started_at)] += w.weight
        for person in w.log.cast or []:
            cast[person] += w.weight

    n = len(weighted)
    share = n / (n + config.COLD_START_K)
    seed = senior.seed_prefs or {}
    ones = lambda items: {k: 1.0 for k in items or []}
    neutral_slots = {name: config.NEUTRAL_TIMESLOT for name, _, _ in config.TIME_BANDS}
    return Profile(
        series=_blend(_normalize(series), ones(seed.get("series")), share),
        cast=_blend(_normalize(cast), ones(seed.get("cast")), share),
        genre=_blend(_normalize(genre), ones(seed.get("genres")), share),
        timeslot=_blend(_normalize(slot), neutral_slots, share),
        history_share=share,
        n_logs=n,
        daily_budget_min=daily_budget_min(logs, today),
        focus_budget_min=focus_budget_min(logs, today),
        on_ratio=on_ratio_by_hour(logs, today),
        usual_channel=usual_channel_by_hour(logs, today),
        left_on_series=_left_on_only(weighted, seed),
        genre_watch_share=genre_watch_share(logs, today),
        genre_seen_share=genre_seen_share(logs, today),
    )
