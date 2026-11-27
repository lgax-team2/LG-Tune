"""빈 시간 채우기: 방송 칸(pick) 사이, 하루 첫 시청 구간 시작~첫 방송, 마지막 방송~취침. 그 시각의 TV 켜짐 단계(tv_pattern)에 따라:

- 높음 → 채우는 순서 (②-4): ① 하루표에 있는 시리즈의 다른 회차 → ② 좋아하는 출연자 → ③ 좋아하는 장르 → ④ 그 시간대 습관
         (그 시각에 하는 방송 중에서, 같은 순서 안에선 점수 높은 것 — 단 지금 채널이 0.1 이내면 지금 채널)
         → ⑤ 취향 하한을 넘는 LG 콘텐츠 → ⑥ 채널 유지(배경 편성: 앞 채널, 없으면 그 시각에 평소 켜 두는 채널)
- 중간 → 짧게만: 앞 채널 이어서 또는 LG 콘텐츠, 합쳐서 MID_FILL_MAX_MIN(20분) 이하
- 낮음 → 비움 ("쉬는 시간"으로 확인 화면에 표시)
이미 시작한 방송은 남은 시간이 절반 이상이고 15분 이상일 때만 (can_join).
LG 조건 (기준표 S9·S10): 취향 점수 ≥ 기준점 × 0.8 (새로 추천 1개는 예외), 하루표 전체 시간 중 LG ≤ 30%, LG 칸 수 < 방송 칸 수.
LG 배정 순서: 새로 추천(S5) → 켜짐 '높음' 첫 자리(S6) → 취향 점수 높은 것부터 (같은 콘텐츠는 하루 한 번).
채운 시간도 하루 총 시간 상한에 들어간다. LG 는 빈자리에만 들어가므로 방송 칸을 밀어내지 않는다 (기준표 M7).
"""

import itertools
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from ..models.db import LgContent, Program
from . import config
from .breaks import Break, after_breaks, in_break
from .genres import genres_of, same_episode
from .plan import BACKGROUND, NORMAL, NOVELTY, Entry
from .preference import Profile
from .rules import RuleSet
from .scoring import Scored, score_lg, score_program
from .tv_pattern import HIGH, LOW


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
    breaks: list[Break] | None = None,
) -> Filled:
    breaks = breaks or []  # 고정 비움 시간: 그 안에서 시작하는 칸 없음
    used = [e.source for e in picks if isinstance(e.source, Program)]  # 이미 나온 회차들
    planned_series = {e.source.series_key for e in picks if isinstance(e.source, Program)}
    left = [
        profile.daily_budget_min - sum(e.minutes for e in picks)
    ]  # 하루 총 시간 중 남은 분 (함께 줄여 감)
    fills: list[Entry] = []
    slots: list[Slot] = []
    keep_later: list[tuple[Slot, str | None]] = []  # LG 뒤에도 남은 '높음' 자리 → 채널 유지
    rests: list[tuple[datetime, datetime]] = []
    for start, end, before in _gaps(picks, viewing_start, sleep):
        if not rules.allows_start(start):
            continue  # "오늘은 그만 볼래" 뒤
        channel = before.channel_id if before else None
        for seg_start, seg_end, tier in _segments(start, end, profile):
            if not rules.allows_start(seg_start):
                break  # "오늘은 그만 볼래" 뒤 구간은 채우지도, 쉬는 시간으로 표시하지도 않음
            if tier == LOW:
                rests.append((seg_start, seg_end))
                channel = None
                continue
            if tier == HIGH:
                channel = channel or profile.usual_channel.get(seg_start.hour)
                chosen, holes, channel = _taste_fill(
                    seg_start, seg_end, channel, usable, used, planned_series, profile, rules, breaks, left
                )
                fills += chosen
                for hole_start, hole_end in holes:  # 건너뛴 틈 → LG 자리, 그래도 남으면 채널 유지
                    hs = after_breaks(hole_start, breaks)
                    if hs < hole_end:
                        first = first_high is not None and hs <= first_high < hole_end
                        slot = Slot(hs, hole_end, tier, first, float("inf"))
                        slots.append(slot)
                        keep_later.append((slot, channel))
                continue
            else:  # 중간: 앞 방송에 바로 붙은 구간만, 채널 이어서 MID_FILL_MAX_MIN 분까지
                prev = channel if seg_start == start else None
                limit = min(seg_end, seg_start + timedelta(minutes=config.MID_FILL_MAX_MIN))
                chosen = _keep_channel(
                    prev, seg_start, limit, usable, used, rules, breaks, left, NORMAL, one=True
                )
                room = config.MID_FILL_MAX_MIN - sum(e.minutes for e in chosen)
            fills += chosen
            t = after_breaks(chosen[-1].end if chosen else seg_start, breaks)
            if t < seg_end and room > 0:
                first = (
                    first_high is not None and t <= first_high < seg_end
                )  # 켜짐 '높음'이 처음 시작되는 자리 (S6)
                slot = Slot(t, seg_end, tier, first, room)
                slots.append(slot)
                if tier == HIGH:
                    keep_later.append((slot, channel))
    base = picks + fills
    lgs, note = _choose_lg(
        slots, lg_contents, profile, rules, floor, base, left[0], novelty_lg_genres, breaks
    )
    left[0] -= sum(e.minutes for e in lgs)
    for slot, channel in keep_later:  # 순서 마지막: 채널 유지 (LG 뒤에도 남은 '높음' 자리)
        if slot.start < slot.end:
            ch = channel or profile.usual_channel.get(slot.start.hour)
            fills += _keep_channel(
                ch, slot.start, slot.end, usable, used, rules, breaks, left, BACKGROUND, one=False
            )
    return Filled(sorted(picks + fills + lgs, key=lambda e: e.start), rests, note)


def can_join(p: Program, t: datetime) -> bool:
    """이미 시작한 방송은 남은 시간이 JOIN_MIN_LEFT_MIN 분 이상이고 전체의 JOIN_MIN_LEFT_RATIO 이상일 때만 넣음."""
    if p.start >= t:
        return True
    left = (p.end - t).total_seconds() / 60
    total = (p.end - p.start).total_seconds() / 60
    return left >= config.JOIN_MIN_LEFT_MIN and left >= config.JOIN_MIN_LEFT_RATIO * total


def _taste_fill(
    start: datetime,
    end: datetime,
    channel: str | None,
    usable: list[Program],
    used: list[Program],
    planned_series: set[str],
    profile: Profile,
    rules: RuleSet,
    breaks: list[Break],
    left: list[float],
) -> tuple[list[Entry], list[tuple[datetime, datetime]], str | None]:
    """'높음' 빈 시간 채우기 1단계: 그 시각에 하는 방송 중 순서대로 — 같은 시리즈 다른 회차 → 좋아하는 출연자
    → 좋아하는 장르 → 그 시간대 습관. 같은 순서 안에선 점수 높은 것, 단 지금 채널이 0.1 이내면 지금 채널.
    그 시각에 맞는 방송이 없으면 다음 방송이 시작하는 시각으로 넘어가며, 건너뛴 틈은 (LG·채널 유지용) 빈자리로 돌려줌."""
    out: list[Entry] = []
    holes: list[tuple[datetime, datetime]] = []
    t = start
    while t < end and rules.allows_start(t):
        if in_break(t, breaks):
            t = after_breaks(t, breaks)  # 고정 비움 시간은 건너뜀 (채우지 않음)
            continue
        on_air = [
            p
            for p in usable
            if p.start <= t < p.end and can_join(p, t) and not any(same_episode(p, u) for u in used)
        ]
        found = _by_fill_order(on_air, t, channel, planned_series, profile)
        if found is None:
            nxt = min((p.start for p in usable if t < p.start < end), default=end)
            holes.append((t, nxt))
            t = nxt
            continue
        p, why, s = found
        stop = min(p.end, end)
        minutes = (stop - t).total_seconds() / 60
        if minutes > left[0]:
            holes.append((t, end))
            break
        role = BACKGROUND if why == "habit" else NORMAL  # 평소 켜 두는 채널 = 배경 편성
        out.append(
            Entry(
                p.id, p.channel_id, p.title, t, stop, 0.0, "fill", scored=s, source=p, role=role, fill_why=why
            )
        )
        used.append(p)
        left[0] -= minutes
        t, channel = stop, p.channel_id
    return out, holes, channel


def _by_fill_order(
    on_air: list[Program], t: datetime, channel: str | None, planned_series: set[str], profile: Profile
):
    """(방송, 고른 까닭, 점수) — 까닭 순서: series(다른 회차) → cast → genre → habit(그 시각에 평소 켜 두는 채널). 없으면 None.
    '틀어만 놓던 시리즈'는 취향 순서(series·cast·genre)에선 빼고 habit 에서만 (결정 D24)."""
    scored = [(p, score_program(p, profile, [])) for p in on_air]
    taste = [(p, s) for p, s in scored if p.series_key not in profile.left_on_series]
    usual = profile.usual_channel.get(t.hour)
    groups = {
        "series": [(p, s) for p, s in taste if p.series_key in planned_series],
        "cast": [(p, s) for p, s in taste if s.parts["cast"] > 0 and s.top_cast],
        "genre": [(p, s) for p, s in taste if s.parts["genre"] > 0 and s.top_genre],
        "habit": [(p, s) for p, s in scored if usual is not None and p.channel_id == usual],
    }
    for why in config.FILL_ORDER:
        members = groups[why]
        if not members:
            continue
        best = max(members, key=lambda ps: (ps[1].score, -ps[0].start.timestamp(), ps[0].id))
        here = [
            ps
            for ps in members
            if ps[0].channel_id == channel and ps[1].score >= best[1].score - config.CHANNEL_TIE_SCORE
        ]
        p, s = here[0] if here else best  # 점수 차 0.1 이내면 지금 채널
        return p, why, s
    return None


def _keep_channel(
    channel: str | None,
    start: datetime,
    end: datetime,
    usable: list[Program],
    used: list[Program],
    rules: RuleSet,
    breaks: list[Break],
    left: list[float],
    role: str,
    one: bool,
) -> list[Entry]:
    """그 채널(앞 방송 채널 또는 평소 켜 두는 채널)에서 이어지는 방송들. one=True 면 한 편만 ('중간' 시각)."""
    out: list[Entry] = []
    if channel is None:
        return out
    t = start
    while t < end and rules.allows_start(t) and not in_break(t, breaks):
        nxt = next(
            (
                p
                for p in usable
                if p.channel_id == channel
                and p.start <= t < p.end
                and can_join(p, t)
                and not any(same_episode(p, u) for u in used)
            ),
            None,
        )
        if nxt is None:
            break
        stop = min(nxt.end, end)
        minutes = (stop - t).total_seconds() / 60
        if minutes > left[0]:
            break
        out.append(Entry(nxt.id, nxt.channel_id, nxt.title, t, stop, 0.0, "fill", source=nxt, role=role))
        used.append(nxt)
        left[0] -= minutes
        t = stop
        if one:
            break
    return out


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
    breaks: list[Break],
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
            and not in_break(slot.start, breaks)  # 고정 비움 시간에 시작하지 않게
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
