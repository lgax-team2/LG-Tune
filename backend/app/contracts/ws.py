"""WebSocket 이벤트 계약 v1.

이 파일이 백엔드 ↔ 프론트 약속의 원본이다.
수정하면 반드시 `pnpm gen` 으로 contracts/ws-events.schema.json 을 다시 만들고,
프론트 담당자 리뷰를 받아야 한다.

공통 봉투(envelope): {"v": 1, "type": "...", "ts": "ISO8601", "id": "uuid", "data": {...}}
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .rest import PlanItem

PROTOCOL_VERSION = 1


def _now() -> datetime:
    return datetime.now().astimezone()


class _Envelope(BaseModel):
    v: Literal[1] = PROTOCOL_VERSION
    ts: datetime = Field(default_factory=_now)
    id: str = Field(default_factory=lambda: str(uuid4()))


# ───────────────────────── 서버 → 화면 ─────────────────────────


class ClockTickData(BaseModel):
    now: datetime = Field(description="시연 시계 기준 현재 시각")
    speed: float = Field(1.0, description="배속 (1 = 실제 시간)")


class ClockTick(_Envelope):
    type: Literal["clock.tick"] = "clock.tick"
    data: ClockTickData


class PlanUpdatedData(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    items: list[PlanItem]


class PlanUpdated(_Envelope):
    type: Literal["plan.updated"] = "plan.updated"
    data: PlanUpdatedData


class BuddyNudgeData(BaseModel):
    """조용한 신호: 화면 구석에 AI 친구 아이콘만 띄운다. 소리 없음.
    사용자가 반응(확인 버튼/"왜?")해야 buddy.say 로 이어진다."""

    nudge_id: str
    kind: Literal["memory", "plan", "info"]
    hint: str = Field(max_length=20, description="아이콘 옆 아주 짧은 글 (예: '지난주 그 배우')")
    expires_in_s: int = Field(15, description="이 시간 안에 반응 없으면 사라짐")


class BuddyNudge(_Envelope):
    type: Literal["buddy.nudge"] = "buddy.nudge"
    data: BuddyNudgeData


class BuddySayData(BaseModel):
    say_id: str
    text: str
    audio_url: str | None = Field(None, description="TTS 음성 파일 경로. None 이면 글만 표시")
    mode: Literal["reply", "proactive", "reminder"] = "reply"
    duration_ms: int | None = None


class BuddySay(_Envelope):
    type: Literal["buddy.say"] = "buddy.say"
    data: BuddySayData


class ListenOpenData(BaseModel):
    window_id: str
    expect: Literal["yesno", "free"] = Field(description="응/아니만 기다리는지, 자유 대화인지")
    timeout_s: int = 8


class ListenOpen(_Envelope):
    type: Literal["listen.open"] = "listen.open"
    data: ListenOpenData


class ListenCloseData(BaseModel):
    window_id: str
    reason: Literal["answered", "timeout", "cancelled"]


class ListenClose(_Envelope):
    type: Literal["listen.close"] = "listen.close"
    data: ListenCloseData


class AsrFinalData(BaseModel):
    window_id: str
    text: str


class AsrFinal(_Envelope):
    type: Literal["asr.final"] = "asr.final"
    data: AsrFinalData


class PlaybackSwitchData(BaseModel):
    channel: str
    program_id: str
    position_s: float = 0


class PlaybackSwitch(_Envelope):
    type: Literal["playback.switch"] = "playback.switch"
    data: PlaybackSwitchData


class PlaybackDuckData(BaseModel):
    """AI 친구가 듣거나 말할 때 TV 소리를 낮춘다 (마이크에 TV 소리가 섞이지 않게)."""

    level: float = Field(ge=0, le=1, description="1 = 원래 볼륨, 0.2 = 크게 줄임")


class PlaybackDuck(_Envelope):
    type: Literal["playback.duck"] = "playback.duck"
    data: PlaybackDuckData


class CardShowData(BaseModel):
    card_id: str
    kind: Literal["relation_map", "verse", "concert", "plan"]
    title: str
    payload: dict[str, Any] = Field(default_factory=dict, description="카드 종류별 내용 (docs/cards.md 참고)")


class CardShow(_Envelope):
    type: Literal["card.show"] = "card.show"
    data: CardShowData


class CardHideData(BaseModel):
    card_id: str


class CardHide(_Envelope):
    type: Literal["card.hide"] = "card.hide"
    data: CardHideData


class TvActionData(BaseModel):
    """AI 친구가 말로 받은 요청을 TV 기능으로 실행 (이지TV 기능을 말로 대신 조작).
    시연에서는 화면이 흉내 내고, 실제 제품에서는 webOS 기능 호출."""

    action_id: str
    action: Literal[
        "channel.set",
        "volume.set",
        "volume.mute",
        "input.switch",
        "display.text_size",
        "display.brightness",
        "app.open",
        "video_call.start",
        "game.open",
        "help.request",
        "power.sleep_timer",
    ]
    params: dict[str, Any] = Field(
        default_factory=dict, description="예: {'channel': 'KBS1'}, {'contact': '큰아들'}"
    )
    spoken: str = Field(description="사용자가 실제로 한 말 (로그·디버그용)")
    confirm_required: bool = Field(False, description="영상통화처럼 되돌리기 어려운 건 한 번 더 확인")


class TvAction(_Envelope):
    type: Literal["tv.action"] = "tv.action"
    data: TvActionData


class MetricsSnapshotData(BaseModel):
    kpis: dict[str, float] = Field(description="지표 이름 → 값. 이름 목록은 docs/DECISIONS.md 의 KPI 표")


class MetricsSnapshot(_Envelope):
    type: Literal["metrics.snapshot"] = "metrics.snapshot"
    data: MetricsSnapshotData


# ───────────────────────── 화면 → 서버 ─────────────────────────


class UiReadyData(BaseModel):
    screen: Literal["tv", "setup", "dashboard"] = "tv"


class UiReady(_Envelope):
    type: Literal["ui.ready"] = "ui.ready"
    data: UiReadyData = Field(default_factory=UiReadyData)


class PlayerStateData(BaseModel):
    channel: str
    program_id: str | None
    position_s: float
    segment: Literal["program", "break", "credits", "idle"] = Field(
        description="지금 구간. break/credits 일 때만 AI 친구가 먼저 말할 수 있음"
    )
    volume: float = Field(ge=0, le=1)


class PlayerState(_Envelope):
    type: Literal["player.state"] = "player.state"
    data: PlayerStateData


class RemotePressData(BaseModel):
    button: Literal[
        "ok",
        "cancel",
        "back",
        "home",
        "ai",
        "input",
        "up",
        "down",
        "left",
        "right",
        "ch_up",
        "ch_down",
        "vol_up",
        "vol_down",
    ] = Field(
        description="리모컨은 선택 사항. 직접 조작 감지와 리모컨 의존도 KPI용 (AI 친구는 음성으로만 부름)"
    )


class RemotePress(_Envelope):
    type: Literal["remote.press"] = "remote.press"
    data: RemotePressData


class NudgeResponseData(BaseModel):
    nudge_id: str
    action: Literal["opened", "ignored", "dismissed"]


class NudgeResponse(_Envelope):
    type: Literal["nudge.response"] = "nudge.response"
    data: NudgeResponseData


ServerEvent = Annotated[
    ClockTick
    | PlanUpdated
    | BuddyNudge
    | BuddySay
    | ListenOpen
    | ListenClose
    | AsrFinal
    | PlaybackSwitch
    | PlaybackDuck
    | CardShow
    | CardHide
    | TvAction
    | MetricsSnapshot,
    Field(discriminator="type"),
]

ClientEvent = Annotated[
    UiReady | PlayerState | RemotePress | NudgeResponse,
    Field(discriminator="type"),
]


class WsContract(BaseModel):
    """스키마 생성용 묶음 (실제 메시지로 쓰지 않음)."""

    server: ServerEvent
    client: ClientEvent
