"""Claude 어댑터. LLM_PROVIDER=claude 이고 backend/.env 에 ANTHROPIC_API_KEY 가 있을 때만 쓴다."""

from .base import Message


class ClaudeLLM:
    def __init__(self, api_key: str, model: str, max_tokens: int = 300) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY 가 비어 있어요. backend/.env 에 넣어주세요.")
        from anthropic import AsyncAnthropic  # 가짜만 쓸 때는 불러오지 않음

        self._client = AsyncAnthropic(api_key=api_key, max_retries=0)  # 재시도는 3초 제한과 충돌
        self.model = model
        self.max_tokens = max_tokens

    async def reply(self, system: str, messages: list[Message]) -> str:
        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=_alternate(messages),
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()


def _alternate(messages: list[Message]) -> list[dict]:
    """Claude는 user/assistant 가 번갈아 와야 하고 user 로 시작해야 함 → 같은 역할이 연달으면 합친다."""
    out: list[dict] = []
    for m in messages:
        if out and out[-1]["role"] == m.role:
            out[-1]["content"] += "\n" + m.text
        else:
            out.append({"role": m.role, "content": m.text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out
