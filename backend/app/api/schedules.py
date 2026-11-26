"""B · 하루표 API.

지금은 0단계 임시: data/sample/schedule_example.json 을 그대로 돌려준다 (모양 약속용).
엔진(app/engine)이 생기면 이 안에서 엔진을 부르도록 바꾼다. 응답 모양은 그대로.
"""

from fastapi import APIRouter, HTTPException

from ..contracts.rest import ScheduleResponse
from ..models.sample import SAMPLE_DIR

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


@router.get("/{senior_id}", response_model=ScheduleResponse)
def get_schedule(senior_id: str, date: str | None = None) -> ScheduleResponse:
    example = ScheduleResponse.model_validate_json((SAMPLE_DIR / "schedule_example.json").read_text("utf-8"))
    if senior_id != example.senior_id or (date and date != example.date):
        raise HTTPException(404, f"아직 예시만 있어요: senior_id={example.senior_id}, date={example.date}")
    return example
