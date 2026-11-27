"""빈 시간 채우기: 방송 칸(pick) 사이와 하루 첫 시청 구간 시작~첫 방송 사이. 그 시각의 TV 켜짐 단계(tv_pattern)에 따라:

- 높음 → 배경 편성: 앞 채널의 다음 방송을 이어 붙임(채널 전환 최소). 뺀 방송·이미 나온 시리즈·켜짐 단계가 바뀌면 끊고,
         남은 자리는 취향 맞는 LG 콘텐츠
- 중간 → 짧게만: 앞 채널 이어서 또는 LG 콘텐츠, 합쳐서 MID_FILL_MAX_MIN(20분) 이하
- 낮음 → 비움 ("쉬는 시간"으로 확인 화면에 표시)
LG 조건 (기준표 S9·S10): 취향 점수 ≥ 기준점 × 0.8 (새로 추천 1개는 예외), 하루표 전체 시간 중 LG ≤ 30%, LG 칸 수 < 방송 칸 수.
LG 배정 순서: 새로 추천(S5) → 하루 첫 시청 구간(S6) → 취향 점수 높은 것부터 (같은 콘텐츠는 하루 한 번).
채운 시간도 하루 총 시간 상한에 들어간다. LG 는 빈자리에만 들어가므로 방송 칸을 밀어내지 않는다 (기준표 M7).
"""

import itertools
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from ..models.db import LgContent, Program
from . import config
from .genres import episode_key, genres_of
from .plan import BACKGROUND, NORMAL, NOVELTY, Entry
from .preference import Profile
from .rules import RuleSet
from .scoring import Scored, score_lg
from .tv_pattern import HIGH, LOW, MID


@dataclass
class Slot:
    """LG 를 넣을 수 있는 빈자리 (같은 켜짐 단계 안)."""

    start: datetime
    end: datetime
    tier: str
    first: bool  # 하루 첫 시청 구간 (S6)
    room: float  # 이 자리에 더 넣을 수 있는 분 ('중간'은 MID_FILL_MAX_MIN 까지)

    @property
    def minutes(self) -> float:
        return min((self.end - self.start).total_seconds() / 60, self.room)


@dataclass
class Filled:
    entries: list[Entry]
    rests: list[tuple[datetime, datetime]] = field(default_factory=list)  # '낮음' 시각의 쉬는 시간
    novelty_note: str | None = None


def first_viewing_moment(wake: datetime, sleep: datetime, hours: set[int]) -> datetime | None:
    """기상 이후 처음으로 시청 시간대(켜짐 '중간' 이상)가 되는 시각 (취침 전까지 없으면 None)."""
    if wake.hour in hours:
        return wake
    for h in range(wake.hour + 1, 24):
        moment = datetime.combine(wake.date(), time(h))
        if h in hours and moment < sleep:
            return moment
    return None


def first_high_moment(wake: datetime, sleep: datetime, profile: Profile) -> datetime | None:
    """기상 이후 처음으로 TV 켜짐 '높음'이 되는 시각 (기준표 S6). 없으면 None."""
    if profile.tier(wake.hour) == HIGH:
        return wake
    for h in range(wake.hour + 1, 24):
        moment = datetime.combine(wake.date(), time(h))
        if profile.tier(h) == HIGH and moment < sleep:
            return moment
    return None


def fill_gaps(
    picks: list[Entry],
    usable: list[Program],
    lg_contents: list[LgContent],
    profile: Profile,
    rules: RuleSet,
    viewing_start: datetime | None,
    floor: float,
    novelty_lg_genres: list[str],
    sleep: datetime | None = None,
    first_high: datetime | None = None,
) -> Filled:
    used_series = {episode_key(e.source) for e in picks if isinstance(e.source, Program)}
    budget = profile.daily_budget_min - sum(e.minutes for e in picks)
    fills: list[Entry] = []
    slots: list[Slot] = []
    rests: list[tuple[datetime, datetime]] = []
    for start, end, before in _gaps(picks, viewing_start, sleep):
        if not rules.allows_start(start):
            continue  # "오늘은 그만 볼래" 뒤
        for seg_start, seg_end, tier in _segments(start, end, profile):
            if not rules.allows_start(seg_start):
                break  # "오늘은 그만 볼래" 뒤 구간은 채우지도, 쉬는 시간으로 표시하지도 않음
            if tier == LOW:
                rests.append((seg_start, seg_end))
                continue
            prev = before if seg_start == start else None  # 앞 방송에 바로 붙은 구간만 채널을 이어 감
            usual = profile.usual_channel.get(seg_start.hour) if tier == HIGH else None
            channel = prev.channel_id if prev else usual  # 앞 채널, 없으면 그 시각에 평소 켜 두는 채널
            chain = _same_channel(channel, seg_start, seg_end, tier, usable, used_series, budget, rules)
            fills += chain
            used = sum(e.minutes for e in chain)
            budget -= used
            t = chain[-1].end if chain else seg_start
            room = (config.MID_FILL_MAX_MIN - used) if tier == MID else float("inf")
            if t < seg_end and room > 0:
                first = (
                    first_high is not None and t <= first_high < seg_end
                )  # 켜짐 '높음'이 처음 시작되는 자리 (S6)
                slots.append(Slot(t, seg_end, tier, first, room))
    base = picks + fills
    lgs, note = _choose_lg(slots, lg_contents, profile, rules, floor, base, budget, novelty_lg_genres)
    return Filled(sorted(base + lgs, key=lambda e: e.start), rests, note)


def _gaps(picks: list[Entry], viewing_start: datetime | None, sleep: datetime | None = None):
    """(시작, 끝, 바로 앞 방송 칸) — 첫 칸 앞 구간은 앞 방송이 없음, 마지막 칸 뒤는 취침까지.
    방송 칸이 하나도 없으면 하루 첫 시청 시각~취침 전체가 빈 시간 (켜 두기만 하는 분도 배경 편성)."""
    if not picks:
        if viewing_start is not None and sleep is not None and viewing_start < sleep:
            yield viewing_start, sleep, None
        return
    if viewing_start is not None and viewing_start < picks[0].start:
        yield viewing_start, picks[0].start, None
    for cur, nxt in itertools.pairwise(picks):
        if cur.end < nxt.start:
            yield cur.end, nxt.start, cur
    if sleep is not None and picks[-1].end < sleep:
        yield picks[-1].end, sleep, picks[-1]


def _segments(start: datetime, end: datetime, profile: Profile):
    """빈 시간을 켜짐 단계가 같은 구간으로 나눈다 (정시마다 단계가 바뀔 수 있음)."""
    t = start
    while t < end:
        tier = profile.tier(t.hour)
        nxt = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        while nxt < end and profile.tier(nxt.hour) == tier:
            nxt += timedelta(hours=1)
        seg_end = min(nxt, end)
        yield t, seg_end, tier
        t = seg_end


def _same_channel(
    channel: str | None,
    start: datetime,
    end: datetime,
    tier: str,
    usable: list[Program],
    used_series: set[str],
    budget: float,
    rules: RuleSet,
) -> list[Entry]:
    """그 채널(앞 방송 채널 또는 평소 켜 두는 채널)에서 이어지는 방송들.
    '높음'은 끊길 때까지 이어 붙이고, '중간'은 MID_FILL_MAX_MIN 분까지 한 편."""
    out: list[Entry] = []
    if channel is None:
        return out
    t = start
    limit = end if tier == HIGH else min(end, start + timedelta(minutes=config.MID_FILL_MAX_MIN))
    while t < limit and rules.allows_start(t):
        nxt = next(
            (
                p
                for p in usable
                if p.channel_id == channel and p.start <= t < p.end and episode_key(p) not in used_series
            ),
            None,
        )
        if nxt is None:
            break
        stop = min(nxt.end, limit)
        if (stop - t).total_seconds() / 60 > budget - sum(e.minutes for e in out):
            break
        role = BACKGROUND if tier == HIGH else NORMAL
        out.append(Entry(nxt.id, nxt.channel_id, nxt.title, t, stop, 0.0, "fill", source=nxt, role=role))
        used_series.add(episode_key(nxt))
        t = stop
        if tier == MID:
            break
    return out


def _has_room(
    slots: list[Slot], lg_contents: list[LgContent], n_picks: int, n_lg: int, budget: float
) -> bool:
    """켜짐 '높음·중간' 빈자리에 가장 짧은 LG 콘텐츠 하나라도 들어갈 여유가 있나 (S10·하루 시간 포함)."""
    shortest = min((c.duration_min for c in lg_contents), default=None)
    return (
        shortest is not None
        and n_lg + 1 < n_picks
        and shortest <= budget
        and any(slot.minutes >= shortest for slot in slots)
    )


def _choose_lg(
    slots: list[Slot],
    lg_contents: list[LgContent],
    profile: Profile,
    rules: RuleSet,
    floor: float,
    base: list[Entry],
    budget: float,
    novelty_genres: list[str],
) -> tuple[list[Entry], str | None]:
    min_score = floor * config.LG_SCORE_RATIO
    n_picks = sum(1 for e in base if e.kind == "pick")
    base_minutes = sum(e.minutes for e in base)
    chosen: list[Entry] = []
    used: set[str] = set()

    def lg_minutes() -> float:
        return sum(e.minutes for e in chosen)

    def allowed(c: LgContent, slot: Slot) -> bool:
        total = base_minutes + lg_minutes() + c.duration_min
        return (
            c.id not in used
            and rules.allows_start(slot.start)  # "그만 볼래" 뒤에 시작하지 않게
            and c.duration_min <= slot.minutes
            and not rules.blocks(None, genres_of(c))
            and len(chosen) + 1 < n_picks  # S10: LG 칸 수 < 방송 칸 수
            and lg_minutes() + c.duration_min <= budget  # 하루 총 시간
            and (lg_minutes() + c.duration_min) / total <= config.LG_SHARE_MAX + 1e-9  # S9 비율
        )

    def options(score_rule: bool) -> list[tuple[Scored, Slot, LgContent]]:
        out = []
        for slot in slots:
            for c in lg_contents:
                if allowed(c, slot):
                    s = score_lg(c, profile, slot.start)
                    if not score_rule or s.score >= min_score:
                        out.append((s, slot, c))
        return sorted(out, key=lambda o: (-o[0].score, o[1].start, o[2].id))

    def take(s: Scored, slot: Slot, c: LgContent, role: str) -> None:
        start = slot.start
        end = start + timedelta(minutes=c.duration_min)
        chosen.append(Entry(c.id, c.source, c.title, start, end, 0.0, "lg", scored=s, source=c, role=role))
        used.add(c.id)
        slot.start = end
        slot.room -= c.duration_min

    def tier_role(slot: Slot) -> str:
        return BACKGROUND if slot.tier == HIGH else NORMAL

    note = None
    if novelty_genres:
        novel = [o for o in options(not config.NOVELTY_LG_SKIPS_SCORE_RULE) if o[2].genre in novelty_genres]
        if novel:
            take(*novel[0], NOVELTY)
        elif not _has_room(slots, lg_contents, n_picks, len(chosen), budget):
            note = "해당 없음: 켜짐 '높음·중간' 구간에 새로 추천을 넣을 여유가 없음 (자리·하루 시간·LG 칸 수)"
        else:
            note = "새로 추천할 장르의 콘텐츠가 남은 빈자리·LG 조건에 맞지 않음"
    first = [o for o in options(True) if o[1].first]
    if first:
        s, slot, c = first[0]
        take(s, slot, c, tier_role(slot))
    while rest := options(True):
        s, slot, c = rest[0]
        take(s, slot, c, tier_role(slot))
    return chosen, note
