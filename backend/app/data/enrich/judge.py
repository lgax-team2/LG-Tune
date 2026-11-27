"""LLM 판단: 규칙으로 안 되는 빈칸·애매한 판단만 맡긴다.

- 정해진 JSON 형식({"value": ..., "confidence": 0~1})으로 받고, 서버가 검사한다. 형식이 틀리면 버린다.
- 판단 결과는 data/epg/cache/llm_cache.json 에 저장해 같은 질문을 다시 하지 않는다 (Git에 안 올림).
- 진짜 LLM 은 나중에 app/llm 의 Claude/OpenAI 연결을 감싸서 쓴다. 테스트는 sources/fake.FakeJudgeLLM.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError

from ..raw_store import CACHE_DIR, ensure_ignored_dir


class JudgeLLM(Protocol):
    def ask_json(self, prompt: str) -> str:
        """질문 → JSON 문자열 답."""
        ...


class Judgment(BaseModel):
    """LLM 이 돌려줘야 하는 모양."""

    value: Any
    confidence: float = Field(ge=0, le=1)


class Judge:
    def __init__(self, llm: JudgeLLM, cache_dir: Path = CACHE_DIR):
        self.llm = llm
        self.cache_path = cache_dir / "llm_cache.json"
        self._cache: dict[str, dict[str, Any]] | None = None

    def ask(self, kind: str, question: dict[str, Any]) -> Judgment | None:
        """판단 하나. 저장된 답이 있으면 LLM 을 부르지 않는다. 형식이 틀리면 None.

        kind 예: "series_key"(회차 묶음), "match"(짝짓기), "genre"(장르), "person"(동명이인)
        TODO: kind 별 질문 문구와 value 모양 검사.
        """
        raise NotImplementedError("LLM 판단은 아직 구현 전")

    @staticmethod
    def cache_key(kind: str, question: dict[str, Any]) -> str:
        raw = json.dumps({"kind": kind, "q": question}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def parse(answer: str) -> Judgment | None:
        """LLM 답 검사. JSON 이 아니거나 모양이 틀리면 None."""
        try:
            return Judgment.model_validate_json(answer)
        except ValidationError:
            return None

    def _save(self) -> None:
        ensure_ignored_dir(self.cache_path.parent)
        self.cache_path.write_text(
            json.dumps(self._cache or {}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
