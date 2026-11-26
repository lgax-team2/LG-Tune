"""엔진 전체 흐름: DB에서 읽기 → 취향 → 점수·배치·빈 시간 → 이유 → plan_items 저장 → API 응답 모양."""

from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..contracts.rest import ScheduleItem, ScheduleResponse
from ..models.db import Channel, LgContent, PlanItem, Program, Senior, UserRule, WatchLog
from .planner import build_plan
from .preference import build_profile
from .reason import make_reason
from .rules import RuleSet


class SeniorNotFound(LookupError):
    pass


def make_schedule(session: Session, senior_id: str, day: date) -> ScheduleResponse:
    senior = session.get(Senior, senior_id)
    if senior is None:
        raise SeniorNotFound(senior_id)
    day_start = datetime.combine(day, time.min)
    programs = list(
        session.scalars(
            select(Program).where(Program.start >= day_start, Program.start < day_start + timedelta(days=1))
        )
    )
    logs = list(
        session.scalars(
            select(WatchLog).where(WatchLog.senior_id == senior_id, WatchLog.started_at < day_start)
        )
    )
    rules = list(session.scalars(select(UserRule).where(UserRule.senior_id == senior_id)))
    lg = list(session.scalars(select(LgContent)))
    numbers = {c.id: c.number for c in session.scalars(select(Channel))}

    profile = build_profile(logs, senior, day)
    entries = build_plan(programs, lg, senior, profile, RuleSet(rules, day), day)

    items = [
        ScheduleItem(
            program_id=e.program_id,
            channel_id=e.channel_id,
            channel_number=numbers.get(e.channel_id),
            title=e.title,
            start=e.start,
            end=e.end,
            score=round(e.score, 3),
            reason=make_reason(e),
            kind=e.kind,
        )
        for e in entries
    ]

    # 하루표 저장 (같은 날 것은 새로 덮어씀)
    session.execute(delete(PlanItem).where(PlanItem.senior_id == senior_id, PlanItem.date == day.isoformat()))
    session.add_all(
        PlanItem(
            senior_id=senior_id,
            date=day.isoformat(),
            program_id=i.program_id,
            score=i.score,
            reason=i.reason,
            kind=i.kind,
        )
        for i in items
    )
    session.commit()
    return ScheduleResponse(senior_id=senior_id, date=day.isoformat(), items=items)
