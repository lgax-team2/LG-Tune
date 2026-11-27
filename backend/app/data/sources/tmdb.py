"""TMDB (보강 2): 시리즈 출연진(고정/게스트 구분)과 인물(동명이인) 확인.

- API 키는 backend/.env → settings 로만 읽는다. settings.py 에 tmdb_api_key 칸이 아직 없음 (공통 PR 필요).
- 이 파일은 TMDB 응답만 받아 온다. 출연진을 방송에 붙이는 판단은 enrich/cast.py.
"""

from typing import Any


class TmdbClient:
    def search_series(self, title: str) -> list[dict[str, Any]]:
        """제목으로 TV 시리즈 후보를 찾는다."""
        raise NotImplementedError("TMDB 연결은 아직 구현 전")

    def series_credits(self, series_id: int) -> dict[str, Any]:
        """시리즈 출연진 원본 (고정 출연·게스트 구분용)."""
        raise NotImplementedError("TMDB 연결은 아직 구현 전")

    def person(self, person_id: int) -> dict[str, Any]:
        """인물 정보 (동명이인 구분용: 생년·대표작 등)."""
        raise NotImplementedError("TMDB 연결은 아직 구현 전")
