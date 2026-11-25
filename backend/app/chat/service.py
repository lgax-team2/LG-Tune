"""대화 에이전트 1단계: 글자로 말 걸기 → 기억 참고 → LLM 답 → 저장.

LLM 이 timeout_s(기본 3초) 안에 답 못 하거나 오류가 나면 고정 멘트로 답한다
(어르신이 TV 앞에서 멍하니 기다리지 않게).
"""

import asyncio
import logging
from dataclasses import dataclass
from functools import lru_cache

from ..llm import LLMAdapter, make_llm
from ..llm.base import Message
from ..memory.store import MemoryStore
from ..settings import settings

log = logging.getLogger(__name__)

FALLBACK_LINE = "아이고, 제가 잠깐 딴생각을 했네요. 한 번만 다시 말씀해 주실래요?"

# 성격(페르소나)은 기획이 정하면 교체. 지금은 중립 표기 "AI 친구".
BASE_PROMPT = (
    "너는 TV 속에 사는 어르신의 AI 친구다. 따뜻하고 존댓말로, 한두 문장으로 짧게 말한다. "
    "모르는 건 지어내지 말고 되묻는다."
)


@dataclass(frozen=True)
class ChatResult:
    reply: str
    fallback: bool  # True = 고정 멘트로 답함


class ChatService:
    def __init__(
        self, store: MemoryStore, llm: LLMAdapter, timeout_s: float = 3.0, history_limit: int = 20
    ) -> None:
        self.store = store
        self.llm = llm
        self.timeout_s = timeout_s
        self.history_limit = history_limit

    def build_system(self) -> str:
        cards = self.store.cards()
        if not cards:
            return BASE_PROMPT
        lines = "\n".join(f"- {c}" for c in cards)
        return f"{BASE_PROMPT}\n\n[이 분에 대해 기억하는 것]\n{lines}"

    async def reply(self, text: str) -> ChatResult:
        history = self.store.recent_messages(self.history_limit)
        self.store.add_message("user", text)
        messages = [*history, Message("user", text)]

        try:
            answer = await asyncio.wait_for(self.llm.reply(self.build_system(), messages), self.timeout_s)
            fallback = not answer
        except TimeoutError:
            log.warning("LLM 응답이 %.1f초를 넘어 고정 멘트로 대체", self.timeout_s)
            answer, fallback = "", True
        except Exception as e:  # noqa: BLE001 — 어떤 오류든 고정 멘트로. 메시지에 키가 섞일 수 있어 종류만 기록
            log.warning("LLM 오류로 고정 멘트로 대체: %s", type(e).__name__)
            answer, fallback = "", True

        if fallback:
            answer = FALLBACK_LINE
        self.store.add_message("assistant", answer, fallback=fallback)
        return ChatResult(reply=answer, fallback=fallback)


@lru_cache
def get_chat_service() -> ChatService:
    """API 에서 쓰는 기본 서비스 (설정값으로 한 번만 만든다). 테스트에서는 바꿔 끼운다."""
    return ChatService(
        store=MemoryStore(settings.db_path),
        llm=make_llm(settings),
        timeout_s=settings.llm_timeout_s,
    )
