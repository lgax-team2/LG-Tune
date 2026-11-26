"""OpenAI 어댑터. LLM_PROVIDER=openai 이고 backend/.env 에 OPENAI_API_KEY·OPENAI_MODEL 이 있을 때만 쓴다."""

from .base import Message


class OpenAILLM:
    def __init__(self, api_key: str, model: str, max_tokens: int = 300) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY 가 비어 있어요. backend/.env 에 넣어주세요.")
        if not model:
            raise ValueError("OPENAI_MODEL 이 비어 있어요. backend/.env 에 모델 이름을 넣어주세요.")
        from openai import AsyncOpenAI  # 가짜만 쓸 때는 불러오지 않음

        self._client = AsyncOpenAI(api_key=api_key, max_retries=0)
        self.model = model
        self.max_tokens = max_tokens

    async def reply(self, system: str, messages: list[Message]) -> str:
        resp = await self._client.chat.completions.create(
            model=self.model,
            max_completion_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": system},
                *({"role": m.role, "content": m.text} for m in messages),
            ],
        )
        return (resp.choices[0].message.content or "").strip()
