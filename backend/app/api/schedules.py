"""B · 하루표 API.

GET /api/schedules/{senior_id}?date=YYYY-MM-DD → 엔진(app/engine/service.make_schedule) 결과.
date 를 안 주면 시연일(DEMO_DATE). DB 가 비어 있으면 공통 샘플을 자동으로 넣는다.

GET /api/schedules/{senior_id}/view?date= → 개발용 "엔진 확인 화면"(HTML). 사람이 하루표를 눈으로 검사하는 용도.
API 약속(contracts)에 안 들어가게 include_in_schema=False. 엔진은 고치지 않고 엔진 함수를 불러 계산한다.
"""

import json
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..contracts.rest import ScheduleResponse
from ..engine import config
from ..engine.preference import Profile, build_profile
from ..engine.rules import RuleSet
from ..engine.scoring import score_program
from ..engine.service import SeniorNotFound, make_schedule
from ..models.db import (
    Program,
    Senior,
    UserRule,
    WatchLog,
    init_db,
    make_engine,
    make_session_factory,
)
from ..models.sample import load_sample
from ..settings import settings

DEMO_DATE = date(2026, 12, 1)  # 시연일

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def open_session(db_path: str | Path) -> Iterator[Session]:
    """db_path 의 DB 를 열어 세션을 준다. 표가 없으면 만들고, 어르신이 한 명도 없으면 샘플을 넣는다."""
    engine = make_engine(db_path)
    try:
        init_db(engine)
        with make_session_factory(engine)() as session:
            if session.scalar(select(func.count()).select_from(Senior)) == 0:
                load_sample(session)
            yield session
    finally:
        engine.dispose()  # 요청마다 파일 연결을 닫음 (Windows 파일 잠금 방지)


def get_session() -> Iterator[Session]:
    yield from open_session(settings.mymode_db_path)


@router.get("/{senior_id}", response_model=ScheduleResponse)
def get_schedule(
    senior_id: str,
    session: Annotated[Session, Depends(get_session)],
    day: Annotated[date | None, Query(alias="date")] = None,
) -> ScheduleResponse:
    try:
        return make_schedule(session, senior_id, day or DEMO_DATE)
    except SeniorNotFound:
        raise HTTPException(404, f"없는 어르신이에요: {senior_id}") from None


# ── 개발용 엔진 확인 화면 ──

VIEW_HTML = Path(__file__).parent / "views" / "schedule_view.html"
DATA_SLOT = "__VIEW_DATA__"
MISSED_REASONS = ("겹침", "기상 전·취침 후", "규칙으로 제외", "기준점 미만")


@router.get("/{senior_id}/view", response_class=HTMLResponse, include_in_schema=False)
def view_schedule(
    senior_id: str,
    session: Annotated[Session, Depends(get_session)],
    day: Annotated[date | None, Query(alias="date")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 5,
) -> HTMLResponse:
    day = day or DEMO_DATE
    try:
        schedule = make_schedule(session, senior_id, day)
    except SeniorNotFound:
        raise HTTPException(404, f"없는 어르신이에요: {senior_id}") from None
    data = build_view_data(session, senior_id, day, schedule, limit)
    # JSON 안의 "<" 를 \u003c 로 바꿔 </script> 가 데이터 중간에서 태그를 닫지 못하게 함
    blob = json.dumps(data, ensure_ascii=False).replace("<", r"\u003c")
    return HTMLResponse(VIEW_HTML.read_text(encoding="utf-8").replace(DATA_SLOT, blob))


def build_view_data(
    session: Session, senior_id: str, day: date, schedule: ScheduleResponse, limit: int = 5
) -> dict:
    """화면에 뿌릴 데이터: 어르신 목록, 취향 요약, 하루표, 점수는 높은데 빠진 방송."""
    senior = session.get(Senior, senior_id)
    assert senior is not None  # make_schedule 이 이미 확인함
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
    rules = RuleSet(list(session.scalars(select(UserRule).where(UserRule.senior_id == senior_id))), day)
    profile = build_profile(logs, senior, day)
    series_title = {p.series_key: p.title for p in programs}

    missed, floor = find_missed(programs, senior, profile, rules, day, schedule, limit)
    return {
        "senior": {
            "id": senior.id,
            "name": senior.name,
            "wake": senior.wake_time,
            "sleep": senior.sleep_time,
        },
        "date": day.isoformat(),
        "seniors": [
            {"id": s.id, "name": s.name} for s in session.scalars(select(Senior).order_by(Senior.id))
        ],
        "profile": {
            "series": [{"name": series_title.get(k, k), "value": v} for k, v in _top3(profile.series)],
            "cast": [{"name": k, "value": v} for k, v in _top3(profile.cast)],
            "genre": [{"name": k, "value": v} for k, v in _top3(profile.genre)],
            "timeslot": [{"name": k, "value": v} for k, v in _top3(profile.timeslot)],
            "n_logs": profile.n_logs,
            "history_share": round(profile.history_share, 3),
        },
        "floor": round(floor, 3),
        "items": [i.model_dump(mode="json") for i in schedule.items],
        "missed": missed,
    }


def _top3(d: dict[str, float]) -> list[tuple[str, float]]:
    return [(k, round(v, 3)) for k, v in sorted(d.items(), key=lambda kv: -kv[1]) if v > 0][:3]


def find_missed(
    programs: list[Program],
    senior: Senior,
    profile: Profile,
    rules: RuleSet,
    day: date,
    schedule: ScheduleResponse,
    limit: int = 5,
) -> tuple[list[dict], float]:
    """오늘 편성 중 하루표에 안 들어간 방송을 점수 순으로, 빠진 이유와 함께. (엔진 planner 와 같은 순서로 판정)"""
    wake = datetime.combine(day, time.fromisoformat(senior.wake_time))
    sleep = datetime.combine(day, time.fromisoformat(senior.sleep_time))
    family = senior.family_picks or []
    scored = [(p, score_program(p, profile, family)) for p in programs]

    def in_day(p: Program) -> bool:
        return wake <= p.start and p.end <= sleep

    def by_rule(p: Program) -> bool:
        return not rules.allows_start(p.start) or rules.blocks(p.series_key, p.genre)

    # 기준점: planner.build_plan 과 같은 계산 (후보가 적으면 상위 MIN_CANDIDATES 번째 점수까지 내림)
    ranked = sorted((s.score for p, s in scored if in_day(p) and not by_rule(p)), reverse=True)
    floor = config.THRESHOLD
    if len(ranked) >= config.MIN_CANDIDATES and ranked[config.MIN_CANDIDATES - 1] < floor:
        floor = ranked[config.MIN_CANDIDATES - 1]

    planned = {i.program_id for i in schedule.items}
    picks = [i for i in schedule.items if i.kind == "pick"]
    out = []
    for p, s in sorted(scored, key=lambda ps: -ps[1].score):
        if p.id in planned:
            continue
        if not in_day(p):
            why = "기상 전·취침 후"
            detail = f"기상 {senior.wake_time} 전" if p.start < wake else f"취침 {senior.sleep_time} 후"
        elif by_rule(p):
            why, detail = "규칙으로 제외", _rule_detail(p, rules)
        elif s.score < floor and not rules.is_pinned(p.series_key):
            why, detail = "기준점 미만", f"기준점 {floor:.3f} 미만"
        else:
            hits = [i.title for i in picks if i.start < p.end and p.start < i.end]
            why = "겹침"
            detail = "겹치는 방송: " + ", ".join(hits) if hits else "배치에서 밀림"
        out.append(
            {
                "program_id": p.id,
                "series_key": p.series_key,
                "channel_id": p.channel_id,
                "title": p.title,
                "start": p.start.isoformat(),
                "end": p.end.isoformat(),
                "score": round(s.score, 3),
                "why": why,
                "detail": detail,
            }
        )
        if len(out) == limit:
            break
    return out, floor


def _rule_detail(p: Program, rules: RuleSet) -> str:
    if not rules.allows_start(p.start):
        return '"오늘은 그만 볼래" 이후'
    if rules.blocks(p.series_key, ""):  # 장르 빼고 시리즈만으로도 막히는지
        return f"뺀 프로그램 ({p.series_key})"
    return f"뺀 장르 ({p.genre})"
