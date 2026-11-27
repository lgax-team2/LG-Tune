"""③ 배치(DP) + ⑤ 빈 시간 채우기.

배치: 기상~취침 사이, 시청 시간대 안에서 "시작"하는(끝은 취침 뒤여도 됨) 점수 0.35(기준점) 이상 후보 중에서
      겹치지 않고 총 시간이 하루 시청 시간 상한 안이면서 "(점수 − 기준점) × min(방송 길이, 60분)" 합이 최대인 조합.
      기준점을 겨우 넘은 방송은 무게가 0 에 가까워서, 여러 개를 합쳐도 겹치는 최애를 밀어내지 못한다.
      "매일 챙겨 줘"(pin) 방송은 시청 시간대와 상관없이 먼저 넣고, 그 시간만큼 상한에서 뺀 나머지로 배치.
      (가중 구간 스케줄링 — 앞에서부터 욕심내서 고르는 것보다 정확)
빈 시간: 방송 사이 — 20분 미만 → 앞 채널 그대로(fill) / 20분 이상 → 들어가는 LG채널·VOD 중 점수 최고(lg, 하루 한 번씩)
         기상~첫 방송 — 20분 미만 → 비움(앞 채널이 없음) / 20분 이상 → LG채널·VOD
         빈 시간이 시청 시간대 밖에서 시작하면 채우지 않음. 맞는 게 없으면 비움
"""

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from ..models.db import LgContent, Program, Senior
from . import config
from .genres import genres_of
from .preference import Profile, band_of
from .rules import RuleSet
from .scoring import Scored, score_lg, score_program


@dataclass
class Candidate:
    key: str
    start: datetime
    end: datetime
    score: float
    floor: float = 0.0  # 기준점. 무게는 기준점을 넘은 만큼으로만 잰다
    pinned: bool = False
    payload: Any = None

    @property
    def weight(self) -> float:
        """배치 무게 = (점수 − 기준점) × min(길이, 60분)."""
        return (self.score - self.floor) * min(self.minutes, config.LENGTH_CAP_MIN)

    @property
    def minutes(self) -> int:
        return round((self.end - self.start).total_seconds() / 60)


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


def select_best(cands: list[Candidate], budget_min: float | None = None) -> list[Candidate]:
    """겹치지 않으면서 무게 합이 최대인 조합 (시작 순). budget_min 을 주면 총 시간(분)도 그 안으로.

    쉬운 설명 (DP = 작은 문제의 답을 표에 적어 두고 키워 가기):
    끝나는 시각 순으로 줄 세운 뒤, "앞에서 j 개만 보고 시간을 t 분까지 쓸 때 얻는 최대 무게"를 표 best[j][t] 에 채운다.
    j 번째 방송은 (안 넣기) best[j-1][t] 와 (넣기) 무게 + best[그 방송 전에 끝나는 개수][t − 길이] 중 큰 쪽.
    표를 다 채운 뒤 거꾸로 따라가며 "넣기"를 고른 방송을 모은다.
    """
    cands = sorted(cands, key=lambda c: (c.end, c.start))
    limit = sum(c.minutes for c in cands) if budget_min is None else max(0, int(budget_min))
    ends = [c.end for c in cands]
    before = [bisect_right(ends, c.start, 0, j) for j, c in enumerate(cands)]  # c 시작 전에 끝나는 후보 수
    best = [[0.0] * (limit + 1)]
    for j, c in enumerate(cands):
        prev, row = best[j], [0.0] * (limit + 1)
        for t in range(limit + 1):
            take = c.weight + best[before[j]][t - c.minutes] if c.minutes <= t else float("-inf")
            row[t] = max(prev[t], take)
        best.append(row)
    chosen, j, t = [], len(cands), limit
    while j > 0:
        c = cands[j - 1]
        if (
            c.minutes <= t
            and c.weight >= 0
            and c.weight + best[before[j - 1]][t - c.minutes] >= best[j - 1][t]
        ):
            chosen.append(c)  # 무게 0 은 손해가 없을 때만 들어감
            t -= c.minutes
            j = before[j - 1]
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


def in_viewing_hours(start: datetime, bands: set[str]) -> bool:
    """평소 TV 를 보는 시간대(Profile.viewing_bands)에 시작하는가."""
    return band_of(start) in bands


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
        and not rules.blocks(p.series_key, genres_of(p))
    ]
    bands = profile.viewing_bands()
    scored = [(p, score_program(p, profile, senior.family_picks or [])) for p in usable]
    floor = candidate_floor([s.score for p, s in scored if in_viewing_hours(p.start, bands)])

    def candidate(p: Program, s: Scored) -> Candidate:
        pinned = rules.is_pinned(p.series_key)
        own_floor = 0.0 if pinned else floor  # pin 은 기준점과 상관없음 (pin 끼리 겹칠 때만 점수로 비교)
        return Candidate(p.id, p.start, p.end, s.score, floor=own_floor, pinned=pinned, payload=(p, s))

    # 1) "매일 챙겨 줘" 방송 먼저 (시청 시간대·기준점과 상관없이, 서로 겹치면 무게 큰 쪽)
    fixed = select_best([candidate(p, s) for p, s in scored if rules.is_pinned(p.series_key)])
    # 2) 남은 시간 예산으로 나머지 배치
    left = profile.daily_budget_min - sum(c.minutes for c in fixed)
    pool = [
        candidate(p, s)
        for p, s in scored
        if not rules.is_pinned(p.series_key)
        and s.score >= floor
        and in_viewing_hours(p.start, bands)
        and not any(_overlaps(p, f) for f in fixed)
    ]
    chosen = sorted(fixed + select_best(pool, left), key=lambda c: c.start)
    picks = [_entry(c.payload[0], c.payload[1], "pick", pinned=c.pinned) for c in chosen]
    return _fill_gaps(picks, usable, lg_contents, profile, rules, wake)


def _overlaps(p: Program, c: Candidate) -> bool:
    return p.start < c.end and c.start < p.end


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
    bands = profile.viewing_bands()

    def may_fill(start: datetime) -> bool:  # 빈 시간은 시청 시간대 안, "그만 볼래" 전에 시작할 때만 채움
        return rules.allows_start(start) and in_viewing_hours(start, bands)

    if picks and may_fill(wake):
        # 기상~첫 방송: 앞 채널이 없으니 짧으면 비우고, 길면 LG 콘텐츠
        morning = _lg_for_gap(wake, picks[0].start, lg_contents, profile, rules, used_lg)
        if morning:
            out.append(morning)
    for cur, nxt in zip(picks, [*picks[1:], None]):
        out.append(cur)
        if nxt is None or nxt.start <= cur.end or not may_fill(cur.end):
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
        if c.duration_min <= gap and c.id not in used_lg and not rules.blocks(None, genres_of(c))
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
