"""U+ 방송 ↔ 스카이라이프 방송 짝짓기.

짝 조건: 같은 채널 + 가까운 시작 시각 + 비슷한 제목.
짝이 맞으면 U+ 방송에 스카이라이프의 출연진·세부 장르·생방송 여부를 붙인다.
애매한 짝(제목이 많이 다름 등)은 enrich/judge.py (LLM) 에 맡긴다.
"""

from .normalize import ProgramDraft


def title_similarity(a: str, b: str) -> float:
    """두 제목이 얼마나 비슷한지 0~1. TODO: 공백·괄호·회차 표기를 지운 뒤 비교."""
    raise NotImplementedError


def merge(uplus: list[ProgramDraft], skylife: list[ProgramDraft]) -> list[ProgramDraft]:
    """U+ 방송 목록을 기준으로 스카이라이프 정보를 붙여 돌려준다.

    지금은 짝짓기 전이라 U+ 목록을 그대로 돌려준다 (TODO: 짝짓기 규칙).
    """
    return uplus
