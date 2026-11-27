"""새로 추천 1칸 (기준표 S5): 아직 거의 안 본 장르 중, 가장 좋아하는 장르와 가까운 것.

- 가까운 장르 표: config.NEAR_GENRES / "거의 안 봄": 시청 시간 중 그 장르 비율 < NOVELTY_MAX_SEEN_SHARE
- "안 볼래"로 뺀 장르는 절대 고르지 않음
- 방송에서 먼저 찾고, 마땅한 방송이 없으면 빈 시간의 LG 콘텐츠에서 찾는다 (gaps.py)
"""

from . import config
from .preference import Profile
from .rules import RuleSet
from .selection import Candidate


def novelty_genres(profile: Profile, rules: RuleSet) -> list[str]:
    """새로 추천할 수 있는 장르 (가까운 순서 그대로). 취향을 모르면 빈 목록."""
    favorite = profile.favorite_genre()
    if favorite is None:
        return []
    return [
        g
        for g in config.NEAR_GENRES.get(favorite, [])
        if profile.genre_seen_share.get(g, 0.0) < config.NOVELTY_MAX_SEEN_SHARE
        and not rules.blocks(None, [g])
    ]


def novelty_choices(cands: list[Candidate], genres: list[str], budget_left: float) -> list[Candidate]:
    """후보 방송 중 새로 추천할 장르이면서 남은 시간 예산에 들어가는 것, 좋은 순서 (점수 높은 순 → 이른 시작 → ID).
    planner 가 이 순서대로 보며 더 높은 목표(장르 비율·3연속)를 해치지 않는 첫 번째를 고른다."""
    fits = [c for c in cands if c.genre in genres and c.minutes <= budget_left]
    return sorted(fits, key=lambda c: (-c.score, c.start, c.key))
