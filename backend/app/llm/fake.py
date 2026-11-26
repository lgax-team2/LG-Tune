"""가짜 LLM: API 키 없이 개발·테스트할 때 쓴다. 네트워크 호출 없음."""

import asyncio

from .base import Message


class FakeLLM:
    def __init__(self, delay_s: float = 0.0, fail: bool = False) -> None:
        self.delay_s = delay_s  # 느린 응답 흉내 (타임아웃 테스트용)
        self.fail = fail  # 오류 흉내
        self.last_system = ""
        self.last_messages: list[Message] = []
        self.last_reply = ""

    async def reply(self, system: str, messages: list[Message]) -> str:
        self.last_system = system
        self.last_messages = list(messages)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.fail:
            raise RuntimeError("가짜 LLM 오류")
        said = messages[-1].text if messages else ""
        self.last_reply = f"(가짜 답) '{said}' 말씀이시죠? 그 얘기 좀 더 들려주세요."
        return self.last_reply
