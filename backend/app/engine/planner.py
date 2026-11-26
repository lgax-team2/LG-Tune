"""③ 배치(DP) + ⑤ 빈 시간 채우기.

배치: 기상~취침 사이에 "시작"하는(끝은 취침 뒤여도 됨) 점수 0.35 이상 후보 중에서
      겹치지 않게 "점수 × min(방송 길이, 60분)" 합이 최대가 되는 조합.
      (가중 구간 스케줄링 — 앞에서부터 욕심내서 고르는 것보다 정확)
빈 시간: 방송 사이 — 20분 미만 → 앞 채널 그대로(fill) / 20분 이상 → 들어가는 LG채널·VOD 중 점수 최고(lg, 하루 한 번씩)
         기상~첫 방송 — 20분 미만 → 비움(앞 채널이 없음) / 20분 이상 → LG채널·VOD
         맞는 게 없으면 비움
"""

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from ..models.db import LgContent, Program, Senior
from . import config
from .preference import Profile
from .rules import RuleSet
from .scoring import Scored, score_lg, score_program


@dataclass
class Candidate:
    key: str
    start: datetime
    end: datetime
    score: float
    pinned: bool = False
    payload: Any = None

    @property
    def weight(self) -> float:
        minutes = (self.end - self.start).total_seconds() / 60
        return self.score * min(minutes, config.LENGTH_CAP_MIN) + (config.PIN_BONUS if self.pinned else 0.0)


@dataclass
class Entry:
    program_id: str
    channel_id: str
    title: str
    start: datetime
    end: datetime
    score: float
    kind: str  # pick | fill | lg
    scored: Scored | None = None
    pinned: bool = False
    source: Any = field(default=None, repr=False)  # Program 또는 LgContent


def select_best(cands: list[Candidate]) -> list[Candidate]:
    """가중 구간 스케줄링: 겹치지 않으면서 weight 합이 최대인 조합 (시작 순으로 돌려줌)."""
    cands = sorted(cands, key=lambda c: (c.end, c.start))
    ends = [c.end for c in cands]
    best = [0.0] * (len(cands) + 1)  # best[j] = 앞 j개만 봤을 때 최대 합
    for j, c in enumerate(cands, start=1):
        p = bisect_right(ends, c.start, 0, j - 1)  # c 시작 전에 끝나는 후보 수
        best[j] = max(best[j - 1], c.weight + best[p])
    chosen, j = [], len(cands)
    while j > 0:
        c = cands[j - 1]
        p = bisect_right(ends, c.start, 0, j - 1)
        if c.weight + best[p] >= best[j - 1] and c.weight > 0:
            chosen.append(c)
            j = p
        else:
            j -= 1
    return sorted(chosen, key=lambda c: c.start)


def _at(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(hhmm))


def wake_and_sleep(senior: Senior, day: date) -> tuple[datetime, datetime]:
    """그날의 기상·취침 시각."""
    return _at(day, senior.wake_time), _at(day, senior.sleep_time)


def starts_in_day(p: Program, wake: datetime, sleep: datetime) -> bool:
    """기상 뒤, 취침 전에 시작하는 방송인가. 끝나는 시간은 보지 않는다 (보다 주무셔도 됨)."""
    return wake <= p.start < sleep


def candidate_floor(scores: list[float]) -> float:
    """후보 기준점. 보통 THRESHOLD, 첫날처럼 기준을 넘는 방송이 MIN_CANDIDATES 개도 안 되면
    점수 MIN_CANDIDATES 등까지 낮춘다 (첫날에도 하루표가 비지 않게)."""
    ranked = sorted(scores, reverse=True)
    if len(ranked) >= config.MIN_CANDIDATES and ranked[config.MIN_CANDIDATES - 1] < config.THRESHOLD:
        return ranked[config.MIN_CANDIDATES - 1]
    return config.THRESHOLD


def build_plan(
    programs: list[Program],
    lg_contents: list[LgContent],
    senior: Senior,
    profile: Profile,
    rules: RuleSet,
    day: date,
) -> list[Entry]:
    wake, sleep = wake_and_sleep(senior, day)
    usable = [
        p
        for p in programs
        if starts_in_day(p, wake, sleep)
        and rules.allows_start(p.start)
        and not rules.blocks(p.series_key, p.genre)
    ]
    scored = [(p, score_program(p, profile, senior.family_picks or [])) for p in usable]
    floor = candidate_floor([s.score for _, s in scored])

    cands = [
        Candidate(p.id, p.start, p.end, s.score, pinned=rules.is_pinned(p.series_key), payload=(p, s))
        for p, s in scored
        if s.score >= floor or rules.is_pinned(p.series_key)
    ]
    picks = [_entry(c.payload[0], c.payload[1], "pick", pinned=c.pinned) for c in select_best(cands)]
    return _fill_gaps(picks, usable, lg_contents, profile, rules, wake)


def _entry(
    p: Program, s: Scored | None, kind: str, pinned: bool = False, end: datetime | None = None
) -> Entry:
    return Entry(
        program_id=p.id,
        channel_id=p.channel_id,
        title=p.title,
        start=p.start,
        end=end or p.end,
        score=s.score if (s and kind == "pick") else 0.0,
        kind=kind,
        scored=s,
        pinned=pinned,
        source=p,
    )


def _fill_gaps(
    picks: list[Entry],
    usable: list[Program],
    lg_contents: list[LgContent],
    profile: Profile,
    rules: RuleSet,
    wake: datetime,
) -> list[Entry]:
    out: list[Entry] = []
    used_lg: set[str] = set()  # 같은 LG 콘텐츠는 하루에 한 번만
    if picks and rules.allows_start(wake):
        # 기상~첫 방송: 앞 채널이 없으니 짧으면 비우고, 길면 LG 콘텐츠
        morning = _lg_for_gap(wake, picks[0].start, lg_contents, profile, rules, used_lg)
        if morning:
            out.append(morning)
    for cur, nxt in zip(picks, [*picks[1:], None]):
        out.append(cur)
        if nxt is None or nxt.start <= cur.end or not rules.allows_start(cur.end):
            continue
        gap = (nxt.start - cur.end).total_seconds() / 60
        if gap < config.SHORT_GAP_MIN:
            # 앞 채널에서 바로 이어지는 방송 (뺀 방송이면 usable 에 없으니 비워 둠)
            same = [p for p in usable if p.channel_id == cur.channel_id and p.start <= cur.end < p.end]
            if same:
                out.append(_entry(same[0], None, "fill", end=min(same[0].end, nxt.start)))
        else:
            filler = _lg_for_gap(cur.end, nxt.start, lg_contents, profile, rules, used_lg)
            if filler:
                out.append(filler)
    return out


def _lg_for_gap(
    start: datetime,
    end: datetime,
    lg_contents: list[LgContent],
    profile: Profile,
    rules: RuleSet,
    used_lg: set[str],
) -> Entry | None:
    """start~end 빈 시간에 들어가는 LG채널·VOD 중 점수 최고 1개 (20분 미만 빈 시간이거나 맞는 게 없으면 None).
    고른 콘텐츠는 used_lg 에 넣어 하루에 한 번만 쓰게 한다."""
    gap = (end - start).total_seconds() / 60
    if gap < config.SHORT_GAP_MIN:
        return None
    fits = [
        (c, score_lg(c, profile, start))
        for c in lg_contents
        if c.duration_min <= gap and c.id not in used_lg and not rules.blocks(None, c.genre)
    ]
    if not fits:
        return None
    c, s = max(fits, key=lambda x: (x[1].score, x[0].duration_min))
    used_lg.add(c.id)
    return Entry(
        program_id=c.id,
        channel_id=c.source,
        title=c.title,
        start=start,
        end=start + timedelta(minutes=c.duration_min),
        score=0.0,
        kind="lg",
        scored=s,
        source=c,
    )
