"""TMDB 로 출연진 보강.

- 시리즈 출연진에서 고정 출연과 게스트를 구분한다 (엔진 점수에는 고정 출연이 중요).
- 같은 이름의 다른 사람(동명이인)은 인물 정보로 가린다. 애매하면 enrich/judge.py (LLM).
- 출연진을 모르면 [] 로 둔다 (엔진이 출연자 항목을 빼고 계산함, 명세 6절 규칙 1).
"""

from ..normalize import ProgramDraft


def add_cast(programs: list[ProgramDraft]) -> list[ProgramDraft]:
    """출연진이 빈 방송에 TMDB 고정 출연진을 붙인다.

    지금은 TMDB 연결 전이라 그대로 돌려준다 (TODO).
    """
    return programs
