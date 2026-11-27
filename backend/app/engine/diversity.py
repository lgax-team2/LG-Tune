"""다양성 검사 (기준표 S2·S4): 한 장르 도배, 같은 장르 연속을 찾는다.

planner 는 여기서 찾은 장르·칸의 배치 무게를 깎아(× REPLAN_PENALTY) 다시 배치한다.
"""

from collections import defaultdict

from . import config
from .preference import Profile
from .selection import Candidate

EPS = 1e-9


def genre_cap(genre: str, profile: Profile) -> float:
    """한 장르가 차지할 수 있는 비율 = max(50%, 그분이 실제로 그 장르를 보는 비율)."""
    return max(config.GENRE_SHARE_MAX, profile.genre_watch_share.get(genre, 0.0))


def genre_minutes_share(items: list) -> dict[str, float]:
    """칸 목록(시간이 있고 genre 를 알 수 있는 것)의 장르별 시간 비율."""
    minutes: dict[str, float] = defaultdict(float)
    for it in items:
        minutes[_genre(it)] += it.minutes
    total = sum(minutes.values())
    return {g: m / total for g, m in minutes.items()} if total else {}


def over_share_genres(counted: list[Candidate], profile: Profile) -> list[str]:
    """비율 상한을 넘은 장르 (이름순). 세는 칸이 GENRE_SHARE_MIN_COUNT(3) 개 미만이면 '해당 없음' → 빈 목록."""
    if len(counted) < config.GENRE_SHARE_MIN_COUNT:
        return []
    shares = genre_minutes_share(counted)
    return sorted(g for g, s in shares.items() if s > genre_cap(g, profile) + EPS)


def long_runs(picks_in_order: list) -> int:
    """같은 장르가 STREAK_MAX 칸을 넘게 이어진 줄의 개수 (고정 칸 포함 — 위반 여부 판단용)."""
    count, run = 0, 0
    for prev, cur in zip([None, *picks_in_order], picks_in_order):
        run = run + 1 if prev is not None and _genre(prev) == _genre(cur) else 1
        count += run == config.STREAK_MAX + 1
    return count


def streak_breakers(picks_in_order: list[Candidate], fixed_keys: set[str]) -> list[Candidate]:
    """같은 장르가 STREAK_MAX 칸을 넘게 이어진 줄의 칸들 (고정 칸은 못 바꾸므로 제외).
    3칸째만 깎으면 "가운데를 다른 장르로 바꾸는" 답을 못 찾기 때문에 줄 전체를 감점한다."""
    out: list[Candidate] = []
    run: list[Candidate] = []
    for c in [*picks_in_order, None]:
        if c is not None and run and _genre(c) == _genre(run[-1]):
            run.append(c)
            continue
        if len(run) > config.STREAK_MAX:
            out += [x for x in run if x.key not in fixed_keys]
        run = [c] if c is not None else []
    return out


def _genre(item) -> str:
    return item.genre if isinstance(item, Candidate) else item.source.genre
