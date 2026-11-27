"""빈 시간 채우기: 방송 칸(pick) 사이와 하루 첫 시청 구간 시작~첫 방송 사이를 채운다.

- 20분 미만 → 앞 채널 그대로(fill). 첫 칸 앞은 앞 채널이 없으니 비움. 같은 시리즈가 이미 있으면 비움 (기준표 M4)
- 20분 이상 → LG채널·VOD (기준표 S9: 취향 점수 ≥ 기준점 × 0.8, 하루표 전체 시간 중 LG ≤ 30%)
  · 배정 순서: 새로 추천(S5) LG → 하루 첫 시청 구간 빈 시간(S6) → 나머지는 취향 점수 높은 것부터 (같은 콘텐츠는 하루 한 번)
  · 새로 추천 LG 1개는 취향 점수 기준 예외 (config.NOVELTY_LG_SKIPS_SCORE_RULE), 비율 상한은 그대로
- 빈 시간이 시청 시간대 밖이나 "오늘은 그만 볼래" 뒤에서 시작하면 채우지 않음
- LG 는 빈 시간에만 들어가므로 방송 칸을 밀어내지 않는다 (기준표 M7)
"""

import itertools
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from ..models.db import LgContent, Program
from . import config
from .genres import genres_of
from .plan import NOVELTY, Entry
from .preference import Profile, band_of
from .rules import RuleSet
from .scoring import score_lg


@dataclass
class Gap:
    start: datetime
    end: datetime
    before: Entry | None  # 빈 시간 바로 앞 방송 칸 (첫 칸 앞이면 None)

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


def first_viewing_moment(wake: datetime, sleep: datetime, bands: set[str]) -> datetime | None:
    """기상 이후 처음으로 시청 시간대가 되는 시각 (취침 전까지 없으면 None)."""
    if band_of(wake) in bands:
        return wake
    day: date = wake.date()
    for name, start_h, _ in config.TIME_BANDS:
        moment = datetime.combine(day, time(start_h))
        if name in bands and wake < moment < sleep:
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
) -> tuple[list[Entry], str | None]:
    """방송 칸 사이를 채운 전체 칸 목록과, 새로 추천 LG 를 못 넣었으면 그 이유."""
    bands = profile.viewing_bands()
    gaps = [
        g for g in _gaps(picks, viewing_start) if rules.allows_start(g.start) and band_of(g.start) in bands
    ]
    used_series = {e.source.series_key for e in picks if isinstance(e.source, Program)}

    fills = []
    for g in gaps:
        if g.minutes < config.SHORT_GAP_MIN and g.before is not None:
            fill = _same_channel(g, usable, used_series)
            if fill:
                fills.append(fill)
                used_series.add(fill.source.series_key)
    base_minutes = sum(e.minutes for e in picks + fills)
    long_gaps = [g for g in gaps if g.minutes >= config.SHORT_GAP_MIN]
    lgs, novelty_note = _choose_lg(
        long_gaps, lg_contents, profile, rules, floor, base_minutes, novelty_lg_genres
    )
    return sorted(picks + fills + lgs, key=lambda e: e.start), novelty_note


def _gaps(picks: list[Entry], viewing_start: datetime | None) -> list[Gap]:
    out = []
    if picks and viewing_start is not None and viewing_start < picks[0].start:
        out.append(Gap(viewing_start, picks[0].start, None))
    for cur, nxt in itertools.pairwise(picks):
        if cur.end < nxt.start:
            out.append(Gap(cur.end, nxt.start, cur))
    return out


def _same_channel(g: Gap, usable: list[Program], used_series: set[str]) -> Entry | None:
    """앞 채널에서 바로 이어지는 방송 (뺀 방송·이미 나온 시리즈면 None)."""
    same = [
        p
        for p in usable
        if p.channel_id == g.before.channel_id
        and p.start <= g.start < p.end
        and p.series_key not in used_series
    ]
    if not same:
        return None
    p = same[0]
    return Entry(p.id, p.channel_id, p.title, g.start, min(p.end, g.end), 0.0, "fill", source=p)


def _choose_lg(
    gaps: list[Gap],
    lg_contents: list[LgContent],
    profile: Profile,
    rules: RuleSet,
    floor: float,
    base_minutes: float,
    novelty_genres: list[str],
) -> tuple[list[Entry], str | None]:
    min_score = floor * config.LG_SCORE_RATIO
    every = []  # (점수, 빈 시간, 콘텐츠) — 들어가는 것 전부
    for g in gaps:
        for c in lg_contents:
            if c.duration_min <= g.minutes and not rules.blocks(None, genres_of(c)):
                every.append((score_lg(c, profile, g.start), g, c))
    every.sort(key=lambda o: (-o[0].score, o[1].start, o[2].id))
    options = [o for o in every if o[0].score >= min_score]  # 취향 점수 기준(S9)을 넘는 것

    chosen: list[Entry] = []
    filled: set[datetime] = set()
    used: set[str] = set()
    lg_minutes = 0.0

    def fits_cap(minutes: float) -> bool:  # LG / (방송 + LG) ≤ LG_SHARE_MAX
        total = base_minutes + lg_minutes + minutes
        return total > 0 and (lg_minutes + minutes) / total <= config.LG_SHARE_MAX + 1e-9

    def take(s, g, c, role) -> None:
        nonlocal lg_minutes
        chosen.append(
            Entry(
                c.id,
                c.source,
                c.title,
                g.start,
                g.start + timedelta(minutes=c.duration_min),
                0.0,
                "lg",
                scored=s,
                source=c,
                role=role,
            )
        )
        filled.add(g.start)
        used.add(c.id)
        lg_minutes += c.duration_min

    def free(o) -> bool:
        return o[1].start not in filled and o[2].id not in used and fits_cap(o[2].duration_min)

    note = None
    if novelty_genres:
        pool = every if config.NOVELTY_LG_SKIPS_SCORE_RULE else options
        novel = [o for o in pool if o[2].genre in novelty_genres and free(o)]
        if novel:
            take(*novel[0], NOVELTY)
        else:
            note = "새로 추천할 장르의 방송·LG 콘텐츠가 남은 시간·빈 시간·LG 비율 조건에 맞지 않음"
    first_gap = [o for o in options if o[1].before is None and free(o)]  # 하루 첫 시청 구간 (S6)
    if first_gap:
        take(*first_gap[0], "normal")
    for o in options:
        if free(o):
            take(*o, "normal")
    return chosen, note
