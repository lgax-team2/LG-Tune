"""엔진 전체 흐름: DB 에서 읽기 → 취향 → 하루표 짜기 → (기준표 판정) → plan_items 저장 → API 응답 모양.

- make_schedule(): 하루표 API 용 (판정 없이 빠르게)
- plan_day(): 확인 화면·테스트용 (기준표 판정까지)
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..contracts.rest import ScheduleItem, ScheduleResponse
from ..models.db import Channel, LgContent, PlanItem, PlanVersion, Program, Senior, UserRule, WatchLog
from .plan import Plan
from .planner import build_plan, wake_and_sleep
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
    numbered_channels: set[str]  # 리모컨 번호가 있는 채널 (기준표 M8)


def load_inputs(session: Session, senior_id: str, day: date) -> DayInputs:
    senior = session.get(Senior, senior_id)
    if senior is None:
        raise SeniorNotFound(senior_id)
    day_start = datetime.combine(day, time.min)
    day_end = max(
        day_start + timedelta(days=1), wake_and_sleep(senior, day)[1]
    )  # 취침이 다음 날이면 그때까지
    programs = list(
        session.scalars(
            select(Program)
            .where(Program.start >= day_start, Program.start < day_end)
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
    numbered = {c.id for c in session.scalars(select(Channel)) if c.number is not None}
    profile = build_profile(logs, senior, day, rules)  # rules: 쉬어가기 되돌리기(unpause)
    return DayInputs(senior, programs, lg, profile, RuleSet(rules, day), day, numbered)


def plan_day(session: Session, senior_id: str, day: date) -> tuple[Plan, Report]:
    """하루표 + 기준표 판정 (확인 화면·테스트용)."""
    i = load_inputs(session, senior_id, day)
    return check_plan(i.programs, i.lg_contents, i.senior, i.profile, i.rules, i.day, i.numbered_channels)


def make_schedule(
    session: Session, senior_id: str, day: date, reason: str = "하루표 조회"
) -> ScheduleResponse:
    """하루표 API 응답을 만들고 plan_items 에 저장한다 (같은 날 것은 새로 덮어씀)."""
    i = load_inputs(session, senior_id, day)
    plan = build_plan(i.programs, i.lg_contents, i.senior, i.profile, i.rules, i.day, i.numbered_channels)
    return save_and_respond(session, senior_id, day, plan, reason)


def save_and_respond(
    session: Session, senior_id: str, day: date, plan: Plan, reason: str = "하루표 조회"
) -> ScheduleResponse:
    """하루표 응답을 만들고 plan_items 를 새로 덮어씀. 칸이 바뀌었으면 변경 기록(plan_versions)에 한 줄."""
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
    record_version(session, senior_id, day, plan, reason)
    session.execute(delete(PlanItem).where(PlanItem.senior_id == senior_id, PlanItem.date == day.isoformat()))
    session.add_all(
        PlanItem(
            senior_id=senior_id,
            date=day.isoformat(),
            program_id=i.program_id,
            score=i.score,
            reason=i.reason,
            kind=i.kind,
            start=i.start,
            end=i.end,
        )
        for i in items
    )
    session.commit()
    return ScheduleResponse(senior_id=senior_id, date=day.isoformat(), items=items)


def record_version(
    session: Session, senior_id: str, day: date, plan: Plan, reason: str
) -> PlanVersion | None:
    """지난 저장본(plan_items)과 비교해 칸이 바뀌었으면 새 버전을 남긴다 (처음이면 버전 1). 안 바뀌었으면 None.
    같은 방송이라도 시작·끝 시각이나 종류(pick/fill/lg)가 바뀌면 '바뀜'."""
    old = {
        i.program_id: (i.kind, i.start, i.end)
        for i in session.scalars(
            select(PlanItem).where(PlanItem.senior_id == senior_id, PlanItem.date == day.isoformat())
        )
    }
    new = {e.program_id: e for e in plan.entries}
    last = session.scalars(
        select(PlanVersion)
        .where(PlanVersion.senior_id == senior_id, PlanVersion.date == day.isoformat())
        .order_by(PlanVersion.version.desc())
    ).first()
    added = [e for pid, e in new.items() if pid not in old]
    removed = sorted(old.keys() - new.keys())
    moved = [e for pid, e in new.items() if pid in old and old[pid] != (e.kind, e.start, e.end)]
    if last is not None and not added and not removed and not moved:
        return None
    changes = (
        [
            {
                "change": "추가",
                "program_id": e.program_id,
                "title": e.title,
                "start": e.start.isoformat(),
                "why": e.reason,
            }
            for e in added
        ]
        + [
            {
                "change": "바뀜",
                "program_id": e.program_id,
                "title": e.title,
                "start": e.start.isoformat(),
                "why": e.reason,
            }
            for e in moved
        ]
        + [
            {
                "change": "빠짐",
                "program_id": pid,
                "title": _title(session, pid),
                "start": "",
                "why": plan.dropped.get(pid, "다시 계산하며 다른 칸으로 바뀜"),
            }
            for pid in removed
        ]
    )
    version = PlanVersion(
        senior_id=senior_id,
        date=day.isoformat(),
        version=(last.version + 1) if last else 1,
        reason=reason,
        changes=changes,
    )
    session.add(version)
    return version


def _title(session: Session, program_id: str) -> str:
    p = session.get(Program, program_id) or session.get(LgContent, program_id)
    return p.title if p else program_id
