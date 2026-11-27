"""① 취향 추정: 시청 기록 + 첫날 정보(관심사) → 취향 점수표(0~1)와 시청 습관.

- 신호 세기: 직접 고름 1.0 / 이어짐·추천 0.3 / 5분 미만·취소 0
- 본 날 기준 반감기: 최근 본 날부터 세어 14번째 본 날의 기록은 절반 (달력 날짜가 아님 — 띄엄띄엄 보는 분도 공평)
- 기록이 적으면 첫날 정보(seed_prefs)를 더 믿음: 기록 비중 = n / (n + 10)
- 장르가 여러 개인 기록은 각 장르에 같은 무게로 더함 (나눠 갖지 않음)
- 시리즈 점수엔 완주 추정 가중치(끝난 이유 별)도 곱함. 같은 시리즈를 자꾸 건너뛰면 7일 쉬어가기 (출연자 점수는 그대로)
- 시간대 습관은 1시간 단위, 그 시각 기록이 적으면 4구간(아침·낮·저녁·밤) 값
- 하루 틀(시청 시간대·하루 총 시간)은 신호 세기와 상관없이 TV 켜짐 패턴으로 (tv_pattern.py)
- 장르별 실제 시청 비율은 직접 고른 시청으로
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..models.db import Senior, UserRule, WatchLog
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
    timeslot_hour: dict[int, float] = field(default_factory=dict)  # 시각(0~23) → 시간대 습관 0~1
    hour_weight: dict[int, float] = field(
        default_factory=dict
    )  # 시각별 기록 무게 합(반감기만) — 적으면 4구간 값
    paused: dict[str, date] = field(default_factory=dict)  # 쉬어가는 시리즈 → 이 날짜 전까지
    genre_watch_share: dict[str, float] = field(
        default_factory=dict
    )  # 대표 장르별 실제 시청 비율 (직접 고른 시청)
    genre_seen_share: dict[str, float] = field(
        default_factory=dict
    )  # 장르 목록 기준, 시청 시간 중 그 장르가 든 비율

    def timeslot_score(self, dt: datetime) -> float:
        """그 시각의 시간대 습관: 1시간 단위 기록이 충분하면 그 시각 값, 아니면 4구간 값."""
        if self.hour_weight.get(dt.hour, 0.0) >= config.TIMESLOT_HOUR_MIN_WEIGHT:
            return self.timeslot_hour.get(dt.hour, 0.0)
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


def paused_series(logs: list[WatchLog], today: date, rules: list[UserRule] | None = None) -> dict[str, date]:
    """반복 거절 쉬어가기: REJECT_WINDOW_DAYS 일 안에 같은 시리즈를 건너뜀·"됐다"(REJECT_REASONS)로
    REJECT_COUNT 번 끝내면, 그 거절 날부터 PAUSE_DAYS 일 동안 쉼 → 지금 쉬는 시리즈 {시리즈: 쉬기 끝나는 날}.
    5분 미만 기록도 세지만 "방금 거 취소"(cancelled) 기록은 안 셈. unpause 규칙이 있으면 그 날까지의 거절은 잊음."""
    forgiven: dict[str, date] = {}
    for r in rules or []:
        if r.active and r.kind == "unpause" and r.target_type == "series" and r.date:
            d = date.fromisoformat(r.date)
            forgiven[r.target] = max(d, forgiven.get(r.target, d))
    rejections: dict[str, list[date]] = defaultdict(list)
    for log in logs:
        d = log.started_at.date()
        if (
            not log.cancelled
            and (log.end_reason or "completed") in config.REJECT_REASONS
            and 0
            < (today - d).days
            <= config.MAX_AGE_DAYS  # 자르는 곳에 따라 "3번 묶음"이 바뀌지 않게 취향 기록 범위(60일) 전체
            and d > forgiven.get(log.series_key, date.min)
        ):
            rejections[log.series_key].append(d)
    out = {}
    for key, days in rejections.items():
        until = _last_pause_end(sorted(days))
        if until is not None and today < until:
            out[key] = until
    return out


def _last_pause_end(days: list[date]) -> date | None:
    """거절 날짜들을 시간 순으로 세다가 REJECT_COUNT 번이 되면 그날부터 PAUSE_DAYS 일 쉬고, 그때까지의 거절은 잊고 다시 셈.
    마지막 쉬어가기가 끝나는 날 (한 번도 안 쉬면 None)."""
    count, until = [], None
    for d in days:
        count = [x for x in count if (d - x).days < config.REJECT_WINDOW_DAYS] + [d]
        if len(count) >= config.REJECT_COUNT:
            until, count = d + timedelta(days=config.PAUSE_DAYS), []
    return until


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


def build_profile(
    logs: list[WatchLog], senior: Senior, today: date, rules: list[UserRule] | None = None
) -> Profile:
    """시청 기록과 첫날 관심사(seed_prefs)를 섞어 취향표를 만든다. 관심사를 바꾸면 다음 계산에 바로 반영된다."""
    weighted = weigh_logs(logs, today)
    series, cast, genre, slot = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float)
    slot_hour, hour_weight = defaultdict(float), defaultdict(float)
    for w in weighted:
        series[w.log.series_key] += w.weight * config.END_REASON_WEIGHT.get(
            w.log.end_reason or "completed", 1.0
        )
        slot_hour[w.log.started_at.hour] += w.weight
        hour_weight[w.log.started_at.hour] += w.weight / config.SIGNAL[w.log.how_started]  # 반감기만
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
        timeslot_hour={
            h: share * v + (1 - share) * config.NEUTRAL_TIMESLOT for h, v in _normalize(slot_hour).items()
        },
        hour_weight=dict(hour_weight),
        paused=paused_series(logs, today, rules),
        usual_channel=usual_channel_by_hour(logs, today),
        left_on_series=_left_on_only(weighted, seed),
        genre_watch_share=genre_watch_share(logs, today),
        genre_seen_share=genre_seen_share(logs, today),
    )
