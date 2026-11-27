"""고정 비움 시간: 식사·약처럼 매일 반복해서 TV 칸을 두지 않는 시간 (가족이 입력, seniors.fixed_breaks).

그 사이에 "시작"하는 칸은 없다 (이미 이어지고 있는 칸은 그대로). 방송·채널 유지·LG 모두 같음.
"""

from datetime import datetime, time

from ..models.db import Senior

Break = tuple[time, time]


def parse_breaks(senior: Senior) -> list[Break]:
    """["12:00-12:30", ...] → [(12:00, 12:30), ...]. 형식이 틀린 값은 무시."""
    out = []
    for text in getattr(senior, "fixed_breaks", None) or []:
        try:
            a, b = (time.fromisoformat(x.strip()) for x in text.split("-"))
        except ValueError:
            continue
        if a < b:
            out.append((a, b))
    return sorted(out)


def in_break(dt: datetime, breaks: list[Break]) -> bool:
    """dt 가 고정 비움 시간 [시작, 끝) 안인가."""
    return any(a <= dt.time() < b for a, b in breaks)


def after_breaks(dt: datetime, breaks: list[Break]) -> datetime:
    """dt 가 비움 시간 안이면 그 비움 시간이 끝나는 시각으로 미룸."""
    for a, b in breaks:
        if a <= dt.time() < b:
            return datetime.combine(dt.date(), b)
    return dt
