"""① 취향 추정: 시청 기록 + 첫날 정보(관심사) → 취향 점수표(0~1)와 시청 습관.

- 신호 세기: 직접 고름 1.0 / 이어짐·추천 0.3 / 5분 미만·취소 0
- 본 날 기준 반감기: 최근 본 날부터 세어 14번째 본 날의 기록은 절반 (달력 날짜가 아님 — 띄엄띄엄 보는 분도 공평)
- 기록이 적으면 첫날 정보(seed_prefs)를 더 믿음: 기록 비중 = n / (n + 10)
- 장르가 여러 개인 기록은 각 장르에 같은 무게로 더함 (나눠 갖지 않음)
- 시청 습관: 시청 시간대, 하루 시청 시간 상한(직접 고른 시청 기준), 장르별 실제 시청 비율
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from ..models.db import Senior, WatchLog
from . import config
from .genres import genres_of


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
    daily_budget_min: float = config.DEFAULT_BUDGET_MIN  # 하루 pick 시간 상한 (분)
    genre_watch_share: dict[str, float] = field(
        default_factory=dict
    )  # 대표 장르별 실제 시청 비율 (직접 고른 시청)
    genre_seen_share: dict[str, float] = field(
        default_factory=dict
    )  # 장르 목록 기준, 시청 시간 중 그 장르가 든 비율

    def timeslot_score(self, dt: datetime) -> float:
        return self.timeslot.get(band_of(dt), 0.0)

    def viewing_bands(self) -> set[str]:
        """평소 TV 를 보는 시간대 (습관 점수 HABIT_BAND_MIN 이상). 습관 정보가 아예 없으면 모든 시간대."""
        all_bands = {name for name, _, _ in config.TIME_BANDS}
        if not self.timeslot:
            return all_bands
        return {b for b in all_bands if self.timeslot.get(b, 0.0) >= config.HABIT_BAND_MIN}

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


def _recent_chosen(logs: list[WatchLog], today: date) -> list[WatchLog]:
    """최근 BUDGET_RECENT_DAYS 일 안의, 직접 고른(chosen) 유효 기록."""
    return [
        w.log
        for w in weigh_logs(logs, today)
        if w.log.how_started in config.BUDGET_SIGNALS
        and (today - w.log.started_at.date()).days <= config.BUDGET_RECENT_DAYS
    ]


def daily_budget_min(logs: list[WatchLog], today: date) -> float:
    """하루 시청 시간 상한 = 최근 14일 동안 직접 고른 시청이 있던 날의 평균 시청 시간(분).
    그런 날이 BUDGET_MIN_DAYS 보다 적으면 기본값(DEFAULT_BUDGET_MIN)."""
    minutes_per_day: dict[date, float] = defaultdict(float)
    for log in _recent_chosen(logs, today):
        minutes_per_day[log.started_at.date()] += log.watched_min
    if len(minutes_per_day) < config.BUDGET_MIN_DAYS:
        return config.DEFAULT_BUDGET_MIN
    return sum(minutes_per_day.values()) / len(minutes_per_day)


def genre_watch_share(logs: list[WatchLog], today: date) -> dict[str, float]:
    """대표 장르별 실제 시청 비율 (최근 직접 고른 시청 시간 기준). 기준표 S2 상한에 씀."""
    minutes: dict[str, float] = defaultdict(float)
    for log in _recent_chosen(logs, today):
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
        genre_watch_share=genre_watch_share(logs, today),
        genre_seen_share=genre_seen_share(logs, today),
    )
