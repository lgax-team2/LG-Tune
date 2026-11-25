"""LG TUNE 백엔드 진입점.

지금은 뼈대: 상태 점검, 편성 조회(가짜), WebSocket(시계 송신).
기능은 docs/DECISIONS.md 순서대로 하나씩 채운다.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from .chat.service import ChatService, get_chat_service
from .contracts.rest import (
    ChatRequest,
    ChatResponse,
    Health,
    PlanItem,
    PlanResponse,
    SetupRequest,
    SetupResponse,
)
from .contracts.ws import ClientEvent, ClockTick, ClockTickData
from .settings import settings

app = FastAPI(title="LG TUNE", version="0.1.0")
_client_event = TypeAdapter(ClientEvent)


@app.get("/healthz", response_model=Health)
def healthz() -> Health:
    return Health(
        status="ok",
        profile=settings.profile,
        llm=settings.llm_provider,
        stt=settings.stt_provider,
        tts=settings.tts_provider,
    )


@app.post("/api/setup", response_model=SetupResponse)
def setup(req: SetupRequest) -> SetupResponse:
    # TODO(be): DB에 저장
    return SetupResponse()


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, service: Annotated[ChatService, Depends(get_chat_service)]) -> ChatResponse:
    if not settings.chat_enabled:
        raise HTTPException(status_code=403, detail="대화 기능이 꺼져 있어요 (CHAT_ENABLED=false)")
    result = await service.reply(req.text)
    return ChatResponse(reply=result.reply, fallback=result.fallback)


@app.get("/api/plan/today", response_model=PlanResponse)
def plan_today() -> PlanResponse:
    # TODO(be): 편성 엔진 연결. 지금은 가짜 1건.
    now = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    item = PlanItem(
        item_id="demo-1",
        start=now + timedelta(hours=1),
        end=now + timedelta(hours=2),
        channel="KBS1",
        program_id="p-gayo-001",
        title="가요무대",
        reason="트로트 좋아하셔서",
    )
    return PlanResponse(date=now.date().isoformat(), items=[item])


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()

    async def send_clock() -> None:
        while True:
            tick = ClockTick(data=ClockTickData(now=datetime.now().astimezone(), speed=settings.clock_speed))
            await socket.send_text(tick.model_dump_json())
            await asyncio.sleep(1)

    task = asyncio.create_task(send_clock())
    try:
        while True:
            raw = await socket.receive_text()
            try:
                event = _client_event.validate_json(raw)
            except ValidationError:
                continue  # 계약에 안 맞는 메시지는 무시
            # TODO(be): event.type 별 처리 (player.state → 말해도 되는 틈 판단 등)
            _ = event
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
