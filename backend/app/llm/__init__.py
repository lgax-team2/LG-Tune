"""설정(LLM_PROVIDER)에 맞는 LLM 어댑터를 만든다."""

from ..settings import Settings
from .base import LLMAdapter, Message
from .fake import FakeLLM

__all__ = ["FakeLLM", "LLMAdapter", "Message", "make_llm"]


def make_llm(s: Settings) -> LLMAdapter:
    # test 프로필에서는 무조건 가짜 (네트워크 호출 금지 규칙)
    if s.profile == "test" or s.llm_provider == "fake":
        return FakeLLM()
    from .claude import ClaudeLLM

    return ClaudeLLM(api_key=s.anthropic_api_key, model=s.claude_realtime_model)
