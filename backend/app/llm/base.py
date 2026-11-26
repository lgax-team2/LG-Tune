"""LLM 어댑터 공통 모양. 가짜(fake)든 Claude든 이 모양만 맞추면 갈아 끼울 수 있다."""

from dataclasses import dataclass
from typing import Literal, Protocol

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    text: str


class LLMAdapter(Protocol):
    async def reply(self, system: str, messages: list[Message]) -> str:
        """system(성격·기억) + 지금까지 대화 → AI 친구의 다음 말."""
        ...
