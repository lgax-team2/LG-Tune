"""편성표 출처 공통 모양. 진짜(U+·스카이라이프)든 가짜든 이 모양만 맞추면 갈아 끼울 수 있다."""

from datetime import date
from typing import Any, Protocol


class ScheduleSource(Protocol):
    """하루치 편성표 원본을 돌려주는 출처."""

    name: str  # 원본 저장 파일 이름에도 씀. 예: "uplus", "skylife"

    def fetch(self, day: date) -> dict[str, Any]:
        """그날 편성표 원본(받은 그대로의 JSON)을 돌려준다. 실패하면 예외를 던진다."""
        ...


class SourceError(Exception):
    """출처에서 편성표를 받지 못함 (네트워크·응답 모양 이상 등). pipeline 이 다음 출처로 넘어간다."""
