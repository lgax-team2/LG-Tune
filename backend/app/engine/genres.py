"""장르 목록 읽기. 외부 편성표는 장르가 여러 개(genres)일 수 있고, 예전 데이터는 대표 장르(genre) 하나뿐이다.
엔진은 어디서나 genres_of() 로만 장르를 읽어서 두 경우를 똑같이 다룬다."""

from typing import Any


def episode_key(item: Any) -> str:
    """같은 '회차'를 가리키는 키 (기준표 M4). 회차 정보(episode)가 있으면 시리즈+회차, 없으면 시리즈."""
    episode = getattr(item, "episode", None)
    return f"{item.series_key}#{episode}" if episode else item.series_key


def genres_of(item: Any) -> list[str]:
    """방송·시청 기록·LG 콘텐츠의 장르 전부. genres 가 비어 있거나 없으면 [대표 장르]."""
    return list(getattr(item, "genres", None) or [item.genre])
