"""B · 하루표 API.

GET /api/schedules/{senior_id}?date=YYYY-MM-DD → 엔진(app/engine/service.make_schedule) 결과.
date 를 안 주면 시연일(DEMO_DATE). DB 가 비어 있으면 공통 샘플을 자동으로 넣는다.
"""

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..contracts.rest import ScheduleResponse
from ..engine.service import SeniorNotFound, make_schedule
from ..models.db import Senior, init_db, make_engine, make_session_factory
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
