"""B · 하루표 API.

GET /api/schedules/{senior_id}?date=YYYY-MM-DD → 엔진(app/engine/service.make_schedule) 결과.
date 를 안 주면 시연일(DEMO_DATE). DB 가 비어 있으면 공통 샘플을 자동으로 넣는다.

GET /api/schedules/{senior_id}/view?date= → 개발용 "엔진 확인 화면"(HTML). 사람이 하루표를 눈으로 검사하는 용도.
API 약속(contracts)에 안 들어가게 include_in_schema=False. 엔진은 고치지 않고 엔진 함수를 불러 계산한다.
"""

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..contracts.rest import ScheduleResponse
from ..engine import planner as P
from ..engine.genres import genres_of
from ..engine.plan import Plan
from ..engine.quality import Report, check_plan
from ..engine.rules import RuleSet
from ..engine.service import DayInputs, SeniorNotFound, load_inputs, make_schedule, save_and_respond
from ..models.db import (
    Base,
    PlanVersion,
    Program,
    Senior,
    UserRule,
    init_db,
    make_engine,
    make_session_factory,
)
from ..models.sample import load_sample
from ..settings import settings

DEMO_DATE = date(2026, 12, 1)  # 시연일

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def open_session(db_path: str | Path) -> Iterator[Session]:
    """db_path 의 DB 를 열어 세션을 준다. 표가 없으면 만들고, 어르신이 한 명도 없으면 샘플을 넣는다.
    DB 구조가 바뀐 뒤의 옛날 DB 파일이면 'pnpm sample' 로 다시 만들라고 안내한다."""
    engine = make_engine(db_path)
    try:
        init_db(engine)
        missing = missing_columns(engine)
        if missing:
            raise HTTPException(
                500,
                f"DB 구조가 옛날 거예요 ({', '.join(missing)} 없음). "
                "루트 폴더에서 `pnpm sample` 로 다시 만들어 주세요 (샘플을 새로 넣음)",
            )
        with make_session_factory(engine)() as session:
            if session.scalar(select(func.count()).select_from(Senior)) == 0:
                load_sample(session)
            yield session
    finally:
        engine.dispose()  # 요청마다 파일 연결을 닫음 (Windows 파일 잠금 방지)


def missing_columns(engine: Engine) -> list[str]:
    """DB 파일에 없는 칸 목록 (예: 'programs.genres'). 구조가 바뀐 뒤 옛날 DB 를 그대로 쓰면 생긴다.
    init_db(create_all) 는 없는 표만 만들고 있는 표에 칸을 더하지 않기 때문."""
    db = inspect(engine)
    out = []
    for table in Base.metadata.sorted_tables:
        have = {c["name"] for c in db.get_columns(table.name)}
        out += [f"{table.name}.{c.name}" for c in table.columns if c.name not in have]
    return out


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
MISSED_REASONS = P.DROP_REASONS
LABELS = {  # 기준표 v3 (backend/app/engine/QUALITY.md)
    "M1": "칸 겹침 없음·시간 순",
    "M2": "'안 볼래' 0 · '챙겨 줘' 100%",
    "M3": "시청 시간대·취침 지킴",
    "M4": "같은 시리즈 하루 1번",
    "M5": "이유 = 실제 근거",
    "M6": "같은 입력 → 같은 하루표",
    "M7": "LG 가 방송을 안 밀어냄",
    "M8": "채널 번호 없는 방송 없음",
    "S1": "오늘의 대표 방송",
    "S2": "한 장르 비율",
    "S3": "하루 시간 상한",
    "S9": "LG 콘텐츠 기준",
    "S10": "LG 칸 < 방송 칸",
    "S8": "채널 전환",
    "S4": "같은 장르 3연속 없음",
    "S5": "새로 추천 1칸",
    "S6": "첫 칸 30분 안",
}


@router.post("/{senior_id}/unpause", include_in_schema=False)
def unpause_series(
    senior_id: str,
    series: str,
    session: Annotated[Session, Depends(get_session)],
    day: Annotated[date | None, Query(alias="date")] = None,
) -> dict:
    """개발용(약속 밖): 반복 거절로 쉬어가는 시리즈 되돌리기 — 그날까지의 거절은 잊고 다시 후보로 (user_rules unpause)."""
    if session.get(Senior, senior_id) is None:
        raise HTTPException(404, f"없는 어르신이에요: {senior_id}")
    rule = UserRule(
        senior_id=senior_id,
        kind="unpause",
        target_type="series",
        target=series,
        date=(day or DEMO_DATE).isoformat(),
    )
    session.add(rule)
    session.commit()
    return {"ok": True}


@router.get("/{senior_id}/view", response_class=HTMLResponse, include_in_schema=False)
def view_schedule(
    senior_id: str,
    session: Annotated[Session, Depends(get_session)],
    day: Annotated[date | None, Query(alias="date")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 5,
) -> HTMLResponse:
    day = day or DEMO_DATE
    try:
        inputs = load_inputs(session, senior_id, day)
    except SeniorNotFound:
        raise HTTPException(404, f"없는 어르신이에요: {senior_id}") from None
    plan, report = check_plan(
        inputs.programs,
        inputs.lg_contents,
        inputs.senior,
        inputs.profile,
        inputs.rules,
        day,
        inputs.numbered_channels,
    )
    schedule = save_and_respond(
        session, senior_id, day, plan, "확인 화면"
    )  # 하루표 API 와 같은 결과·같은 저장
    data = build_view_data(session, inputs, plan, report, schedule, limit)
    # JSON 안의 "<" 를 \u003c 로 바꿔 </script> 가 데이터 중간에서 태그를 닫지 못하게 함
    blob = json.dumps(data, ensure_ascii=False).replace("<", r"\u003c")
    return HTMLResponse(VIEW_HTML.read_text(encoding="utf-8").replace(DATA_SLOT, blob))


def build_view_data(
    session: Session,
    inputs: DayInputs,
    plan: Plan,
    report: Report,
    schedule: ScheduleResponse,
    limit: int = 5,
) -> dict:
    """화면에 뿌릴 데이터: 기준표 판정, 가치 지표, 취향 요약, 하루표, 빠진 방송과 이유 (엔진 기록 그대로)."""
    senior, profile = inputs.senior, inputs.profile
    series_title = {p.series_key: p.title for p in inputs.programs}
    used = sum((i.end - i.start).total_seconds() / 60 for i in schedule.items)  # 하루표 전체 (기준표 S3)
    return {
        "senior": {
            "id": senior.id,
            "name": senior.name,
            "wake": senior.wake_time,
            "sleep": senior.sleep_time,
        },
        "date": inputs.day.isoformat(),
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
            "pref_source": senior.pref_source,
        },
        "floor": round(plan.floor, 3),
        "budget": {
            "limit_min": round(plan.budget_min),
            "focus_min": round(inputs.profile.focus_budget_min or plan.budget_min),
            "used_min": round(used),
            "lower_min": round(plan.budget_min * P.config.BUDGET_LOWER_RATIO),
        },
        "viewing_hours": hour_ranges(plan.hours),
        "tiers": {h: profile.tier(h) for h in range(24)},
        "pattern_known": profile.pattern_known,
        "rests": [{"start": a.isoformat(), "end": b.isoformat()} for a, b in plan.rests],
        "quality": {
            part: [
                {"code": c, "label": LABELS[c], "ok": chk.ok, "detail": chk.detail}
                for c, chk in checks.items()
            ]
            for part, checks in (("must", report.must), ("goals", report.goals))
        },
        "metrics": report.metrics,
        "hint": "관심사를 고르면 더 잘 맞춰요" if not plan.knows_taste else "",
        "items": [i.model_dump(mode="json") for i in schedule.items],
        "roles": {e.program_id: e.role for e in plan.entries},
        "paused": [
            {"series_key": k, "title": series_title.get(k, k), "until": until.isoformat()}
            for k, until in sorted(profile.paused.items())
        ],
        "fixed_breaks": list(senior.fixed_breaks or []),
        "versions": [
            {
                "version": v.version,
                "at": v.created_at.isoformat(timespec="seconds"),
                "reason": v.reason,
                "changes": v.changes,
            }
            for v in session.scalars(
                select(PlanVersion)
                .where(PlanVersion.senior_id == senior.id, PlanVersion.date == inputs.day.isoformat())
                .order_by(PlanVersion.version.desc())
                .limit(10)
            )
        ],
        "missed": find_missed(inputs, plan, limit),
    }


def hour_ranges(hours: set[int]) -> list[str]:
    """{9, 10, 11, 19, 20} → ["09–12시", "19–21시"] (끝 시각은 그 시각 전까지)."""
    out, run = [], []
    for h in sorted(hours):
        if run and h != run[-1] + 1:
            out.append(f"{run[0]:02d}–{run[-1] + 1:02d}시")
            run = []
        run.append(h)
    if run:
        out.append(f"{run[0]:02d}–{run[-1] + 1:02d}시")
    return out


def _top3(d: dict[str, float]) -> list[tuple[str, float]]:
    return [(k, round(v, 3)) for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0])) if v > 0][:3]


def find_missed(inputs: DayInputs, plan: Plan, limit: int = 5) -> list[dict]:
    """오늘 편성 중 하루표에 없는 방송을 점수 순으로. 빠진 이유는 엔진이 배치하며 남긴 기록(Plan.dropped)."""
    planned = {e.program_id for e in plan.entries}
    out = []
    for p in sorted(inputs.programs, key=lambda p: (-plan.scores.get(p.id, 0.0), p.start, p.id)):
        if p.id in planned:
            continue
        why = plan.dropped.get(p.id, P.OVERLAP)
        out.append(
            {
                "program_id": p.id,
                "series_key": p.series_key,
                "channel_id": p.channel_id,
                "title": p.title,
                "start": p.start.isoformat(),
                "end": p.end.isoformat(),
                "score": round(plan.scores.get(p.id, 0.0), 3),
                "why": why,
                "detail": _detail(why, p, inputs, plan),
            }
        )
        if len(out) == limit:
            break
    return out


def _detail(why: str, p: Program, inputs: DayInputs, plan: Plan) -> str:
    senior = inputs.senior
    if why == P.OUT_OF_DAY:
        wake, _ = P.wake_and_sleep(senior, inputs.day)
        return f"기상 {senior.wake_time} 전" if p.start < wake else f"취침 {senior.sleep_time} 후"
    if why == P.BY_RULE:
        return _rule_detail(p, inputs.rules)
    if why == P.OFF_HOURS:
        return "평소 TV 를 켜는 시각: " + ", ".join(hour_ranges(plan.hours))
    if why == P.BELOW_FLOOR:
        return f"기준점 {plan.floor:.3f} 미만"
    if why in (P.OVERLAP, P.PIN_CLASH):
        hits = [e.title for e in plan.picks() if e.start < p.end and p.start < e.end]
        return "겹치는 방송: " + ", ".join(hits) if hits else "배치에서 밀림"
    return {
        P.NO_TASTE: "취향을 몰라 새 회차·생방송만 골라요",
        P.NO_NUMBER: "리모컨 채널 번호가 없는 채널이라 틀어 드릴 수 없음",
        P.GENRE_SWAP: "다시 배치해도 장르 비율이 상한을 넘어서, 이 칸은 다른 장르 LG 콘텐츠로 바꿈",
        P.FIXED_BREAK: "매일 비우는 시간: " + ", ".join(inputs.senior.fixed_breaks or []),
        P.PAUSED: f"최근 {P.config.REJECT_WINDOW_DAYS}일에 {P.config.REJECT_COUNT}번 건너뛰셔서 "
        f"{inputs.profile.paused.get(p.series_key, inputs.day):%m/%d} 전까지 쉬어 가요",
        P.LEFT_ON: "평소 틀어만 두시는 방송 — 집중 시청 말고 배경 편성 후보",
        P.SAME_SERIES: "같은 시리즈가 이미 하루표에 있어요",
        P.BUDGET: f"하루 시간 상한 {plan.budget_min:.0f}분",
        P.DIVERSITY: "한 장르 비율·같은 장르 연속 조건",
        P.BUDGET_AND_DIVERSITY: f"하루 시간 상한 {plan.budget_min:.0f}분 + 장르 조건",
        P.CHANNEL: "앞 칸과 같은 채널 방송으로 바꿈",
    }.get(why, "")


def _rule_detail(p: Program, rules: RuleSet) -> str:
    if not rules.allows_start(p.start):
        return '"오늘은 그만 볼래" 이후'
    if rules.blocks(p.series_key, []):  # 장르 빼고 시리즈만으로도 막히는지
        return f"뺀 프로그램 ({p.series_key})"
    return f"뺀 장르 ({', '.join(g for g in genres_of(p) if rules.blocks(None, [g]))})"
