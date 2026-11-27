"""엔진 전체 흐름: DB 에서 읽기 → 취향 → 하루표 짜기 → (기준표 판정) → plan_items 저장 → API 응답 모양.

- make_schedule(): 하루표 API 용 (판정 없이 빠르게)
- plan_day(): 확인 화면·테스트용 (기준표 판정까지)
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..contracts.rest import ScheduleItem, ScheduleResponse
from ..models.db import Channel, LgContent, PlanItem, Program, Senior, UserRule, WatchLog
from .plan import Plan
from .planner import build_plan
from .preference import Profile, build_profile
from .quality import Report, check_plan
from .rules import RuleSet


class SeniorNotFound(LookupError):
    pass


@dataclass
class DayInputs:
    """하루표 계산에 들어가는 것 전부 (항상 같은 순서로 읽음 — 기준표 M6)."""

    senior: Senior
    programs: list[Program]
    lg_contents: list[LgContent]
    profile: Profile
    rules: RuleSet
    day: date


def load_inputs(session: Session, senior_id: str, day: date) -> DayInputs:
    senior = session.get(Senior, senior_id)
    if senior is None:
        raise SeniorNotFound(senior_id)
    day_start = datetime.combine(day, time.min)
    programs = list(
        session.scalars(
            select(Program)
            .where(Program.start >= day_start, Program.start < day_start + timedelta(days=1))
            .order_by(Program.start, Program.channel_id, Program.id)
        )
    )
    logs = list(
        session.scalars(
            select(WatchLog)
            .where(WatchLog.senior_id == senior_id, WatchLog.started_at < day_start)
            .order_by(WatchLog.started_at, WatchLog.id)
        )
    )
    rules = list(
        session.scalars(select(UserRule).where(UserRule.senior_id == senior_id).order_by(UserRule.id))
    )
    lg = list(session.scalars(select(LgContent).order_by(LgContent.id)))
    return DayInputs(senior, programs, lg, build_profile(logs, senior, day), RuleSet(rules, day), day)


def plan_day(session: Session, senior_id: str, day: date) -> tuple[Plan, Report]:
    """하루표 + 기준표 판정 (확인 화면·테스트용)."""
    i = load_inputs(session, senior_id, day)
    return check_plan(i.programs, i.lg_contents, i.senior, i.profile, i.rules, i.day)


def make_schedule(session: Session, senior_id: str, day: date) -> ScheduleResponse:
    """하루표 API 응답을 만들고 plan_items 에 저장한다 (같은 날 것은 새로 덮어씀)."""
    i = load_inputs(session, senior_id, day)
    plan = build_plan(i.programs, i.lg_contents, i.senior, i.profile, i.rules, i.day)
    return save_and_respond(session, senior_id, day, plan)


def save_and_respond(session: Session, senior_id: str, day: date, plan: Plan) -> ScheduleResponse:
    numbers = {c.id: c.number for c in session.scalars(select(Channel))}
    items = [
        ScheduleItem(
            program_id=e.program_id,
            channel_id=e.channel_id,
            channel_number=numbers.get(e.channel_id),
            title=e.title,
            start=e.start,
            end=e.end,
            score=round(e.score, 3),
            reason=e.reason,
            kind=e.kind,
        )
        for e in plan.entries
    ]
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
