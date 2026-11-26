"""REST 계약 v1 (요청·응답 모양)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SetupRequest(BaseModel):
    """자녀 폰 첫 설정."""

    call_name: str = Field(description="AI 친구가 부를 호칭 (예: '어머니', '영숙 님')")
    wake_time: str = Field("06:30", pattern=r"^\d{2}:\d{2}$")
    sleep_time: str = Field("22:00", pattern=r"^\d{2}:\d{2}$")
    favorite_genres: list[str] = Field(default_factory=list, description="예: ['트로트', '사극']")
    favorite_people: list[str] = Field(default_factory=list, description="좋아하는 가수·배우")
    religion: Literal["none", "christian", "catholic", "buddhist"] = "none"


class SetupResponse(BaseModel):
    ok: bool = True


class BreakSegment(BaseModel):
    start_s: float
    end_s: float
    kind: Literal["ad", "credits"]


class EpgProgram(BaseModel):
    program_id: str
    channel: str
    title: str
    start: datetime
    end: datetime
    genre: str
    cast: list[str] = Field(default_factory=list)
    breaks: list[BreakSegment] = Field(
        default_factory=list, description="광고·엔딩 구간 (AI 친구가 말해도 되는 틈)"
    )
    video_url: str | None = None


class PlanItem(BaseModel):
    item_id: str
    start: datetime
    end: datetime
    channel: str
    program_id: str
    title: str
    reason: str = Field(description="고른 이유 (화면 표시용, 예: '트로트 좋아하셔서')")
    status: Literal["planned", "reminded", "accepted", "declined", "playing", "done", "skipped"] = "planned"


class PlanResponse(BaseModel):
    date: str
    items: list[PlanItem]


class ScheduleItem(BaseModel):
    """하루표의 한 칸 (마이모드)."""

    program_id: str
    channel_id: str = Field(description="예: 'KBS1'")
    channel_number: int = Field(description="리모컨 채널 번호")
    title: str
    start: datetime = Field(description="한국 시간, 시간대 표기 없음")
    end: datetime
    score: float = Field(description="엔진 점수 (fill 이면 0)")
    reason: str = Field(description="화면에 보여 줄 고른 이유")
    kind: Literal["pick", "fill"] = Field(description="pick = 점수로 고름, fill = 빈 시간 채움")


class ScheduleResponse(BaseModel):
    senior_id: str
    date: str = Field(description="YYYY-MM-DD")
    items: list[ScheduleItem] = Field(description="시작 시각 순, 서로 겹치지 않음")


class ChatRequest(BaseModel):
    """글자로 AI 친구에게 말 걸기 (음성 연결 전 1단계)."""

    text: str = Field(min_length=1, max_length=500, description="사용자가 한 말")


class ChatResponse(BaseModel):
    reply: str = Field(description="AI 친구의 답")
    fallback: bool = Field(description="true = AI가 제때 답하지 못해 고정 멘트로 답함")


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    profile: str
    llm: str
    stt: str
    tts: str
