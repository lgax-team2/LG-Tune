"""TV 켜짐 패턴: 시청 기록으로 "몇 시에 TV 가 켜져 있는지"와 "하루에 얼마나 켜 두는지"를 읽는다.

취향 점수와 달리 여기서는 신호 세기를 보지 않는다 — 직접 고름·추천으로 봄·틀어만 놓음 모두 100% (5분 미만·취소만 제외).
- 켜짐 비율(시 단위) = 최근 14일 중 기록이 있는 날들의 평균으로, 그 시각 1시간 중 TV 가 켜져 있던 분 / 60
  (같은 시각에 겹친 기록은 한 번만 셈)
- 하루 켜짐 시간 = 기록이 있는 날의 평균 켜짐 분
- 기록이 있는 날이 PATTERN_MIN_DAYS 보다 적으면 "패턴 모름" → 기상~취침 전부 '중간', 하루 시간은 기본값
"""

from collections import defaultdict
from datetime import date

from ..models.db import WatchLog
from . import config

HIGH, MID, LOW = "높음", "중간", "낮음"


def _valid(log: WatchLog, today: date) -> bool:
    return (
        not log.cancelled
        and log.watched_min >= config.MIN_WATCH_MIN
        and 0 < (today - log.started_at.date()).days <= config.PATTERN_RECENT_DAYS
    )


def on_minutes_by_day(logs: list[WatchLog], today: date) -> dict[date, set[int]]:
    """날짜 → 그날 TV 가 켜져 있던 분들의 집합 (시작한 날 기준. 자정을 넘으면 1440 이상으로 이어서 셈)."""
    days: dict[date, set[int]] = defaultdict(set)
    for log in logs:
        if not _valid(log, today):
            continue
        start = log.started_at.hour * 60 + log.started_at.minute
        days[log.started_at.date()].update(range(start, start + round(log.watched_min)))
    return days


def on_ratio_by_hour(logs: list[WatchLog], today: date) -> dict[int, float]:
    """시각(0~23) → 켜짐 비율(0~1). 패턴을 모르면(기록 있는 날 < PATTERN_MIN_DAYS) 빈 사전."""
    days = on_minutes_by_day(logs, today)
    if len(days) < config.PATTERN_MIN_DAYS:
        return {}
    per_hour: dict[int, int] = defaultdict(int)
    for minutes in days.values():
        for m in minutes:
            per_hour[(m // 60) % 24] += 1  # 자정 넘은 분은 다음 날 0시대로
    return {h: per_hour.get(h, 0) / (60 * len(days)) for h in range(24)}


def daily_on_minutes(logs: list[WatchLog], today: date) -> float:
    """하루 켜짐 시간(분) = 기록 있는 날의 평균. 패턴을 모르면 DEFAULT_BUDGET_MIN."""
    days = on_minutes_by_day(logs, today)
    if len(days) < config.PATTERN_MIN_DAYS:
        return config.DEFAULT_BUDGET_MIN
    return sum(len(m) for m in days.values()) / len(days)


def usual_channel_by_hour(logs: list[WatchLog], today: date) -> dict[int, str]:
    """시각 → 그 시각에 가장 오래 켜 둔 채널 (첫 빈 시간처럼 '앞 채널'이 없을 때 배경 편성에 씀). 패턴을 모르면 빈 사전."""
    if len(on_minutes_by_day(logs, today)) < config.PATTERN_MIN_DAYS:
        return {}
    minutes: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for log in logs:
        if not _valid(log, today):
            continue
        start = log.started_at.hour * 60 + log.started_at.minute
        for m in range(start, start + round(log.watched_min)):
            minutes[(m // 60) % 24][log.channel_id] += 1
    return {h: min(chs, key=lambda ch: (-chs[ch], ch)) for h, chs in minutes.items()}


def tier_of(on_ratio: dict[int, float], hour: int) -> str:
    """그 시각의 켜짐 단계. 패턴을 모르면 '중간'(보수적)."""
    if not on_ratio:
        return MID
    r = on_ratio.get(hour, 0.0)
    return HIGH if r >= config.ON_HIGH else (MID if r >= config.ON_MID else LOW)
