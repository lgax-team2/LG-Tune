"""② 점수: 방송(또는 LG 콘텐츠) 하나 → 0~1 점수와 항목별 내역."""

from dataclasses import dataclass
from datetime import datetime

from ..models.db import LgContent, Program
from . import config
from .preference import Profile


@dataclass(frozen=True)
class Scored:
    score: float
    parts: dict[str, float]  # 항목별 기여 (가중치 곱한 값) → 고른 이유 만들 때 씀
    top_cast: str | None  # 가장 좋아하는 출연자


def _score(
    profile: Profile,
    series_key: str | None,
    cast: list[str],
    genre: str,
    when: datetime,
    fresh: bool,
    family: bool,
) -> Scored:
    liked = {p: profile.cast.get(p, 0.0) for p in cast}
    top_cast = max(liked, key=liked.get) if liked and max(liked.values()) > 0 else None
    w = config.WEIGHTS
    parts = {
        "series": w["series"] * (profile.series.get(series_key, 0.0) if series_key else 0.0),
        "cast": w["cast"] * (liked[top_cast] if top_cast else 0.0),
        "genre": w["genre"] * profile.genre.get(genre, 0.0),
        "timeslot": w["timeslot"] * profile.timeslot_score(when),
        "fresh": w["fresh"] * (1.0 if fresh else 0.0),
        "family": w["family"] * (1.0 if family else 0.0),
    }
    return Scored(score=sum(parts.values()), parts=parts, top_cast=top_cast)


def score_program(p: Program, profile: Profile, family_picks: list[str]) -> Scored:
    return _score(
        profile,
        series_key=p.series_key,
        cast=p.cast or [],
        genre=p.genre,
        when=p.start,
        fresh=bool(p.is_new or p.is_live),
        family=p.series_key in (family_picks or []),
    )


def score_lg(c: LgContent, profile: Profile, when: datetime) -> Scored:
    return _score(
        profile, series_key=None, cast=c.cast or [], genre=c.genre, when=when, fresh=False, family=False
    )
