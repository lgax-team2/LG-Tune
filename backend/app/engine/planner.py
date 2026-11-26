"""③ 배치(DP) + ⑤ 빈 시간 채우기.

배치: 기상~취침 안, 점수 0.35 이상 후보 중에서 겹치지 않게 "점수 × min(방송 길이, 60분)" 합이 최대가 되는 조합.
      (가중 구간 스케줄링 — 앞에서부터 욕심내서 고르는 것보다 정확)
빈 시간: 20분 미만 → 앞 채널 그대로(fill) / 20분 이상 → 들어가는 LG채널·VOD 중 점수 최고(lg, 하루 한 번씩) / 없으면 비움
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


def build_plan(
    programs: list[Program],
    lg_contents: list[LgContent],
    senior: Senior,
    profile: Profile,
    rules: RuleSet,
    day: date,
) -> list[Entry]:
    wake, sleep = _at(day, senior.wake_time), _at(day, senior.sleep_time)
    usable = [
        p
        for p in programs
        if wake <= p.start
        and p.end <= sleep
        and rules.allows_start(p.start)
        and not rules.blocks(p.series_key, p.genre)
    ]
    scored = [(p, score_program(p, profile, senior.family_picks or [])) for p in usable]

    # 첫날처럼 정보가 적어 후보가 너무 적으면 기준점을 낮춰 상위 몇 개는 넣는다 (첫날에도 하루표)
    ranked = sorted((s.score for _, s in scored), reverse=True)
    floor = config.THRESHOLD
    if len(ranked) >= config.MIN_CANDIDATES and ranked[config.MIN_CANDIDATES - 1] < floor:
        floor = ranked[config.MIN_CANDIDATES - 1]

    cands = [
        Candidate(p.id, p.start, p.end, s.score, pinned=rules.is_pinned(p.series_key), payload=(p, s))
        for p, s in scored
        if s.score >= floor or rules.is_pinned(p.series_key)
    ]
    picks = [_entry(c.payload[0], c.payload[1], "pick", pinned=c.pinned) for c in select_best(cands)]
    return _fill_gaps(picks, usable, lg_contents, profile, rules)


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
    picks: list[Entry], usable: list[Program], lg_contents: list[LgContent], profile: Profile, rules: RuleSet
) -> list[Entry]:
    out: list[Entry] = []
    used_lg: set[str] = set()  # 같은 LG 콘텐츠는 하루에 한 번만
    for i, cur in enumerate(picks):
        out.append(cur)
        if i + 1 == len(picks):
            break
        nxt = picks[i + 1]
        gap = (nxt.start - cur.end).total_seconds() / 60
        if gap <= 0 or not rules.allows_start(cur.end):
            continue
        if gap < config.SHORT_GAP_MIN:
            # 앞 채널에서 바로 이어지는 방송 (뺀 방송이면 비워 둠)
            same = [p for p in usable if p.channel_id == cur.channel_id and p.start <= cur.end < p.end]
            if same:
                out.append(_entry(same[0], None, "fill", end=min(same[0].end, nxt.start)))
        else:
            fits = [
                (c, score_lg(c, profile, cur.end))
                for c in lg_contents
                if c.duration_min <= gap and c.id not in used_lg and not rules.blocks(None, c.genre)
            ]
            if fits:
                c, s = max(fits, key=lambda x: (x[1].score, x[0].duration_min))
                used_lg.add(c.id)
                out.append(
                    Entry(
                        program_id=c.id,
                        channel_id=c.source,
                        title=c.title,
                        start=cur.end,
                        end=cur.end + timedelta(minutes=c.duration_min),
                        score=0.0,
                        kind="lg",
                        scored=s,
                        source=c,
                    )
                )
    return out
