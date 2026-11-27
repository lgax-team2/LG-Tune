"""② 점수: 방송(또는 LG 콘텐츠) 하나 → 0~1 점수와 항목별 내역.

- 장르 점수 = 장르 목록 중 가장 좋아하는 것 하나
- 출연자 정보가 없으면(빈 목록) 출연자 칸 = MISSING_CAST_SCORE (기본 0 = 모르는 출연자와 같음).
  기준표 S7: 출연자 취향과 상관없는 방송은 출연자 칸을 지워도 점수가 거의 같아야 함
"""

from dataclasses import dataclass
from datetime import datetime

from ..models.db import LgContent, Program
from . import config
from .genres import genres_of
from .preference import Profile


@dataclass(frozen=True)
class Scored:
    score: float
    parts: dict[str, float]  # 항목별 기여 (가중치 곱한 값) → 고른 이유 만들 때 씀
    top_cast: str | None  # 가장 좋아하는 출연자
    top_genre: str | None = None  # 장르 목록 중 가장 좋아하는 장르


def _score(
    profile: Profile,
    series_key: str | None,
    cast: list[str],
    genres: list[str],
    when: datetime,
    fresh: bool,
    family: bool,
) -> Scored:
    top_cast = _best_liked(cast, profile.cast)
    top_genre = _best_liked(genres, profile.genre)
    w = config.WEIGHTS
    parts = {
        "series": w["series"] * (profile.series.get(series_key, 0.0) if series_key else 0.0),
        "cast": w["cast"]
        * (profile.cast[top_cast] if top_cast else (0.0 if cast else config.MISSING_CAST_SCORE)),
        "genre": w["genre"] * (profile.genre[top_genre] if top_genre else 0.0),
        "timeslot": w["timeslot"] * profile.timeslot_score(when),
        "fresh": w["fresh"] * (1.0 if fresh else 0.0),
        "family": w["family"] * (1.0 if family else 0.0),
    }
    return Scored(score=sum(parts.values()), parts=parts, top_cast=top_cast, top_genre=top_genre)


def _best_liked(names: list[str], liked: dict[str, float]) -> str | None:
    """names 중 취향 점수가 가장 높은 것 (아무것도 0 보다 크지 않으면 None)."""
    best = max(names, key=lambda n: liked.get(n, 0.0), default=None)
    return best if best is not None and liked.get(best, 0.0) > 0 else None


def score_program(p: Program, profile: Profile, family_picks: list[str]) -> Scored:
    return _score(
        profile,
        series_key=p.series_key,
        cast=p.cast or [],
        genres=genres_of(p),
        when=p.start,
        fresh=bool(p.is_new or p.is_live),
        family=p.series_key in (family_picks or []),
    )


def score_lg(c: LgContent, profile: Profile, when: datetime) -> Scored:
    return _score(
        profile,
        series_key=None,
        cast=c.cast or [],
        genres=genres_of(c),
        when=when,
        fresh=False,
        family=False,
    )
