"""① 취향 추정: 시청 기록 + 첫날 정보 → 취향 점수표 (0~1).

- 신호 세기: 직접 고름 1.0 / 이어짐·추천 0.3 / 5분 미만·취소 0
- 본 날 기준 반감기: 최근 본 날부터 세어 14번째 본 날의 기록은 절반 (달력 날짜가 아님)
- 기록이 적으면 첫날 정보(seed_prefs)를 더 믿음: 기록 비중 = n / (n + 10)
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from ..models.db import Senior, WatchLog
from . import config


def band_of(dt: datetime) -> str:
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

    def timeslot_score(self, dt: datetime) -> float:
        return self.timeslot.get(band_of(dt), 0.0)


def weigh_logs(logs: list[WatchLog], today: date) -> list[WeightedLog]:
    """취향 계산에 쓸 기록과 그 무게. 버릴 기록은 빠진다."""
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
    return [
        WeightedLog(
            lg,
            config.SIGNAL[lg.how_started] * 0.5 ** (rank[lg.started_at.date()] / config.HALF_LIFE_VIEW_DAYS),
        )
        for lg in kept
    ]


def _normalize(d: dict[str, float]) -> dict[str, float]:
    top = max(d.values(), default=0.0)
    return {k: v / top for k, v in d.items()} if top > 0 else {}


def _blend(history: dict[str, float], seed: dict[str, float], share: float) -> dict[str, float]:
    keys = history.keys() | seed.keys()
    return {k: share * history.get(k, 0.0) + (1 - share) * seed.get(k, 0.0) for k in keys}


def build_profile(logs: list[WatchLog], senior: Senior, today: date) -> Profile:
    weighted = weigh_logs(logs, today)
    series, cast, genre, slot = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float)
    for w in weighted:
        series[w.log.series_key] += w.weight
        genre[w.log.genre] += w.weight
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
    )
