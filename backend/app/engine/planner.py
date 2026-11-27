"""하루표 짜기: 오늘 편성 + 취향 + 규칙 → 하루표(Plan). 기준표는 QUALITY.md.

순서 (앞 단계가 우선 — 기준표 우선순위와 같음):
1. 후보 거르기: 기상~취침 사이 시작, "안 볼래"·"그만 볼래" 아님, 시청 시간대 안 ("챙겨 줘" 예외)
2. 먼저 넣기: "챙겨 줘"(pin) → 오늘의 대표 방송(S1). 넣은 시간만큼 하루 시간 예산에서 뺌
3. 배치(DP): 남은 예산 안에서 무게 합 최대 (selection.py). 같은 시리즈는 무게가 가장 큰 회차 하나만 후보(M4)
4. 다양성(S2·S4): 넘친 장르의 가장 약한 칸·3연속 줄의 칸 무게를 깎아 다시 배치 (최대 MAX_REPLANS 번, 못 지키면 위반이 가장 적은 결과)
5. 채널 유지(S8): 앞 칸과 같은 채널에 거의 비슷한 방송이 있으면 그걸로 바꿈 (다른 기준을 해치지 않을 때만)
6. 새로 추천(S5): 남은 시간·빈자리에 들어가는 방송 1개 (없으면 7 에서 LG 콘텐츠로)
7. 빈 시간 채우기(gaps.py) → 8. 이유 붙이기(reason.py)
하루표에 못 들어간 방송은 이유를 Plan.dropped 에, 못 지킨 목표는 Plan.notes 에 남긴다.
"""

from dataclasses import dataclass
from datetime import date, datetime, time

from ..models.db import LgContent, Program, Senior
from . import config
from .diversity import long_runs, over_share_genres, streak_breakers
from .gaps import fill_gaps, first_viewing_moment
from .genres import genres_of
from .novelty import novelty_choices, novelty_genres
from .plan import NORMAL, NOVELTY, PIN, REPRESENTATIVE, Entry, Plan
from .preference import Profile, band_of
from .reason import explain
from .rules import RuleSet
from .scoring import Scored, score_program
from .selection import Candidate, overlaps, select_best

# 빠진 이유 (확인 화면 "빠진 방송")
OUT_OF_DAY = "기상 전·취침 후"
BY_RULE = "규칙으로 제외"
OFF_HOURS = "시청 시간대 밖"
NO_TASTE = "취향 정보 없음"
BELOW_FLOOR = "기준점 미만"
SAME_SERIES = "같은 시리즈"
OVERLAP = "겹침"
PIN_CLASH = "겹치는 챙겨 줘"
BUDGET = "시간 상한"
DIVERSITY = "다양성"
BUDGET_AND_DIVERSITY = "시간 상한·다양성"
CHANNEL = "채널 유지"
DROP_REASONS = (
    OUT_OF_DAY,
    BY_RULE,
    OFF_HOURS,
    NO_TASTE,
    BELOW_FLOOR,
    SAME_SERIES,
    OVERLAP,
    PIN_CLASH,
    BUDGET,
    DIVERSITY,
    BUDGET_AND_DIVERSITY,
    CHANNEL,
)


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


def pin_rank(p: Program, s: Scored) -> tuple:
    """'챙겨 줘'끼리 비교 순서: 점수 높은 것 → 이른 시작 → ID (작을수록 앞)."""
    return (-s.score, p.start, p.id)


def resolve_pins(scored: list[tuple[Program, Scored]], rules: RuleSet) -> list[Candidate]:
    """'챙겨 줘' 방송 확정 (기준점·시청 시간대와 상관없음, 기준표 M2·M4):
    좋은 순서(pin_rank)대로 보면서, 같은 시리즈가 이미 있거나 이미 고른 pin 과 겹치면 건너뛴다."""
    pinned = sorted(
        ((p, s) for p, s in scored if rules.is_pinned(p.series_key)), key=lambda ps: pin_rank(*ps)
    )
    kept: list[Candidate] = []
    for p, s in pinned:
        if any(k.series_key == p.series_key or overlaps(p, k) for k in kept):
            continue
        kept.append(_candidate(p, s, 0.0))
    return sorted(kept, key=lambda c: c.start)


@dataclass
class _Day:
    """하루표를 짜는 동안 쓰는 값 묶음."""

    profile: Profile
    rules: RuleSet
    bands: set[str]
    floor: float
    budget_left: float
    dropped: dict[str, str]
    notes: dict[str, str]


def build_plan(
    programs: list[Program],
    lg_contents: list[LgContent],
    senior: Senior,
    profile: Profile,
    rules: RuleSet,
    day: date,
) -> Plan:
    programs = sorted(programs, key=lambda p: (p.start, p.channel_id, p.id))  # 같은 입력 → 같은 결과 (M6)
    lg_contents = sorted(lg_contents, key=lambda c: c.id)
    wake, sleep = wake_and_sleep(senior, day)
    bands = profile.viewing_bands()
    knows_taste = profile.knows_taste
    family = senior.family_picks or []
    scored = [(p, score_program(p, profile, family)) for p in programs]
    dropped: dict[str, str] = {}

    # 1) 후보 거르기
    usable = []  # 기상~취침, 규칙 통과 (채널 유지 칸에도 씀)
    for p, s in scored:
        if not starts_in_day(p, wake, sleep):
            dropped[p.id] = OUT_OF_DAY
        elif not rules.allows_start(p.start) or rules.blocks(p.series_key, genres_of(p)):
            dropped[p.id] = BY_RULE
        else:
            usable.append((p, s))
    eligible = []  # 점수로 고를 수 있는 방송: 시청 시간대 안 (+ 취향을 모르면 새 회차·생방송만)
    for p, s in usable:
        if rules.is_pinned(p.series_key):
            continue
        if not in_viewing_hours(p.start, bands):
            dropped[p.id] = OFF_HOURS
        elif not knows_taste and not (p.is_new or p.is_live):
            dropped[p.id] = NO_TASTE
        else:
            eligible.append((p, s))
    floor = candidate_floor([s.score for _, s in eligible])
    d = _Day(profile, rules, bands, floor, profile.daily_budget_min, dropped, {})

    # 2) 먼저 넣기: 챙겨 줘 → 대표 방송
    fixed: list[tuple[Candidate, str]] = [(c, PIN) for c in resolve_pins(usable, rules)]
    kept_pins = {c.key for c, _ in fixed}
    for p, _ in usable:
        if rules.is_pinned(p.series_key) and p.id not in kept_pins:
            same = any(c.series_key == p.series_key for c, _ in fixed)
            dropped[p.id] = SAME_SERIES if same else PIN_CLASH
    rep = _representative(eligible, fixed, d)
    if rep:
        fixed.append((rep, REPRESENTATIVE))
    d.budget_left -= sum(c.minutes for c, _ in fixed)
    if d.budget_left < 0:
        d.notes["S3"] = "대표 방송·챙겨 줘만으로 하루 시간 상한을 넘음 (우선순위가 더 높음)"
    open_cands = _open_candidates(eligible, fixed, d)

    # 3)~5) 배치 + 다양성 + 채널 유지
    pool = _one_per_series(_above_floor(open_cands, d), d)
    chosen = _place_with_diversity(pool, fixed, d)
    chosen = _prefer_same_channel(chosen, pool, fixed, d)
    _record_unchosen(pool, chosen, fixed, d)

    # 6) 새로 추천: 남은 시간·빈자리에 들어가는 방송 (우선순위가 낮아 배치가 끝난 뒤에)
    novel_genres = novelty_genres(profile, rules)
    if not knows_taste:
        d.notes["S5"] = "해당 없음: 아직 취향을 몰라 가까운 장르를 정할 수 없음"
    elif not novel_genres:
        d.notes["S5"] = "가장 좋아하는 장르와 가까운 장르 중 아직 안 본 장르가 없음"
    taken = [c for c, _ in fixed] + chosen
    room = d.budget_left - sum(c.minutes for c in chosen)
    free = [
        c
        for c in open_cands
        if c not in chosen
        and not any(overlaps(c, t) for t in taken)
        and c.series_key not in {t.series_key for t in taken}
    ]
    novel = _novelty_keeping_diversity(novelty_choices(free, novel_genres, room), chosen, fixed, d)
    if novel:
        fixed.append((novel, NOVELTY))
    elif novel_genres and "S5" not in d.notes and free:
        d.notes["S5"] = "새로 추천할 방송을 넣으면 장르 비율·3연속(더 높은 목표)이 나빠짐"

    # 6) 빈 시간 → 7) 이유
    picks = sorted(
        [_entry(c, role) for c, role in fixed] + [_entry(c, NORMAL) for c in chosen], key=lambda e: e.start
    )
    need_lg_novelty = novel_genres if (knows_taste and not novel) else []
    entries, lg_note = fill_gaps(
        picks,
        [p for p, _ in usable],
        lg_contents,
        profile,
        rules,
        first_viewing_moment(wake, sleep, bands),
        floor,
        need_lg_novelty,
    )
    if lg_note and "S5" not in d.notes:
        d.notes["S5"] = lg_note
    favorite = profile.favorite_genre()
    for e in entries:
        r = explain(e, knows_taste, favorite)
        e.reason, e.basis = r.text, r.basis
    return Plan(
        entries=entries,
        floor=floor,
        budget_min=profile.daily_budget_min,
        bands=bands,
        knows_taste=knows_taste,
        favorite_genre=favorite,
        scores={p.id: s.score for p, s in scored},
        dropped={k: v for k, v in dropped.items() if k not in {e.program_id for e in entries}},
        notes=d.notes,
        day=day,
    )


def _novelty_keeping_diversity(
    choices: list[Candidate], chosen: list[Candidate], fixed: list[tuple[Candidate, str]], d: _Day
) -> Candidate | None:
    """새로 추천 후보 중, 넣어도 다양성(S2·S4 — S5 보다 높은 목표) 위반이 늘지 않는 첫 번째."""
    before = _violations(chosen, fixed, d).count()
    for c in choices:
        after = _violations(chosen, [*fixed, (c, NOVELTY)], d).count()
        if after[0] <= before[0] and after[1] <= before[1]:
            return c
    return None


def _minute(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _candidate(p: Program, s: Scored, floor: float) -> Candidate:
    return Candidate(
        p.id,
        p.start,
        p.end,
        s.score,
        floor=floor,
        genre=p.genre,
        series_key=p.series_key,
        channel_id=p.channel_id,
        payload=(p, s),
    )


def _representative(eligible, fixed: list[tuple[Candidate, str]], d: _Day) -> Candidate | None:
    """오늘의 대표 방송 (S1): 시리즈 취향 1위(REPRESENTATIVE_MIN_SERIES 이상)의 새 회차가 시청 시간대 안에 있을 때."""
    if not d.profile.series:
        d.notes["S1"] = "해당 없음: 아직 좋아하는 시리즈를 모름"
        return None
    top_key, top = min(d.profile.series.items(), key=lambda kv: (-kv[1], kv[0]))
    if top < config.REPRESENTATIVE_MIN_SERIES:
        d.notes["S1"] = f"해당 없음: 시리즈 취향 1위 점수 {top:.2f} < {config.REPRESENTATIVE_MIN_SERIES}"
        return None
    if d.rules.is_pinned(top_key):
        d.notes["S1"] = "해당 없음: 시리즈 취향 1위가 이미 '챙겨 줘'로 들어감"
        return None
    episodes = [
        (p, s)
        for p, s in eligible
        if p.series_key == top_key and p.is_new and not any(overlaps(p, c) for c, _ in fixed)
    ]
    if not episodes:
        d.notes["S1"] = f"해당 없음: 시리즈 취향 1위({top_key})의 새 회차가 오늘 시청 시간대 안에 없음"
        return None
    p, s = episodes[0]  # 이른 시작
    return _candidate(p, s, d.floor)


def _open_candidates(eligible, fixed: list[tuple[Candidate, str]], d: _Day) -> list[Candidate]:
    """먼저 넣은 칸과 겹치지 않고, 그 시리즈가 아직 안 나온 후보."""
    used_series = {c.series_key for c, _ in fixed}
    out = []
    for p, s in eligible:
        if p.id in {c.key for c, _ in fixed}:
            continue
        if p.series_key in used_series:
            d.dropped[p.id] = SAME_SERIES
        elif any(overlaps(p, c) for c, _ in fixed):
            d.dropped[p.id] = OVERLAP
        else:
            out.append(_candidate(p, s, d.floor))
    return out


def _above_floor(cands: list[Candidate], d: _Day) -> list[Candidate]:
    out = []
    for c in cands:
        if c.score >= d.floor:
            out.append(c)
        else:
            d.dropped[c.key] = BELOW_FLOOR
    return out


def _one_per_series(cands: list[Candidate], d: _Day) -> list[Candidate]:
    """같은 시리즈는 무게가 가장 큰 회차 하나만 (같으면 이른 시작 → ID). 기준표 M4."""
    best: dict[str, Candidate] = {}
    for c in cands:
        cur = best.get(c.series_key)
        if cur is None or (-c.base_weight, c.start, c.key) < (-cur.base_weight, cur.start, cur.key):
            best[c.series_key] = c
    keep = {id(c) for c in best.values()}
    for c in cands:
        if id(c) not in keep:
            d.dropped[c.key] = SAME_SERIES
    return [c for c in cands if id(c) in keep]


@dataclass
class _Violations:
    over: list[str]  # 비율 넘친 장르 (S2)
    runs: int  # 같은 장르 3연속 줄 수 (S4, 고정 칸 포함)
    breakers: list[Candidate]  # 3연속 줄에서 감점할 칸 (고정 칸 제외)

    def count(self) -> tuple[int, int]:
        return len(self.over), self.runs


def _violations(chosen: list[Candidate], fixed: list[tuple[Candidate, str]], d: _Day) -> _Violations:
    """다양성 위반. 비율은 대표 방송·챙겨 줘를 빼고 셈, 3연속은 모든 방송 칸으로 셈."""
    counted = chosen + [c for c, role in fixed if role == NOVELTY]
    in_order = sorted(chosen + [c for c, _ in fixed], key=lambda c: c.start)
    return _Violations(
        over_share_genres(counted, d.profile),
        long_runs(in_order),
        streak_breakers(in_order, {c.key for c, _ in fixed}),
    )


def _place_with_diversity(
    pool: list[Candidate], fixed: list[tuple[Candidate, str]], d: _Day
) -> list[Candidate]:
    """시간 예산 DP → 다양성을 어기면 칸 무게를 REPLAN_PENALTY 배로 깎아 다시 (최대 MAX_REPLANS 번).
    - 비율 넘친 장르: 그 장르에서 고른 칸 중 가장 약한 칸 하나만 (장르 전체를 깎으면 "전부 트로트 ↔ 전부 다큐"로 오락가락함)
    - 3연속: 그 줄의 칸 전부"""
    key_factor: dict[str, float] = {}
    best, best_rank, best_factors = [], None, {}
    for _ in range(config.MAX_REPLANS):
        for c in pool:
            c.factor = key_factor.get(c.key, 1.0)
        chosen = select_best(pool, max(d.budget_left, 0))
        v = _violations(chosen, fixed, d)
        rank = (*v.count(), -sum(c.base_weight for c in chosen))
        if best_rank is None or rank < best_rank:
            best, best_rank, best_factors = chosen, rank, {c.key: c.factor for c in pool}
        if v.count() == (0, 0):
            break
        for g in v.over:
            weakest = min(
                (c for c in chosen if c.genre == g), key=lambda c: (c.weight, -_minute(c.start), c.key)
            )
            key_factor[weakest.key] = key_factor.get(weakest.key, 1.0) * config.REPLAN_PENALTY
        for c in v.breakers:
            key_factor[c.key] = key_factor.get(c.key, 1.0) * config.REPLAN_PENALTY
    v = _violations(best, fixed, d)
    if v.over:
        d.notes["S2"] = f"다시 배치해도 비율을 못 맞춤 ({', '.join(v.over)}) — 후보가 부족함"
    if v.runs:
        d.notes["S4"] = "다시 배치해도 같은 장르 3연속을 못 피함 — 후보가 부족함"
    for c in pool:  # 채택한 배치의 감점을 남겨 둠 (빠진 이유 판정에 씀)
        c.factor = best_factors.get(c.key, 1.0)
    return best


def _prefer_same_channel(
    chosen: list[Candidate], pool: list[Candidate], fixed: list[tuple[Candidate, str]], d: _Day
) -> list[Candidate]:
    """S8: 앞 칸과 채널이 다르면, 앞 칸 채널에서 같은 자리에 들어가는 후보 중 (무게 + 가산)이 더 큰 것으로 바꾼다.
    바꾼 뒤 시간 예산·같은 시리즈·다양성이 나빠지면 바꾸지 않음."""
    fixed_keys = {c.key for c, _ in fixed}
    i = 0
    while True:
        i += 1
        in_order = sorted(chosen + [c for c, _ in fixed], key=lambda c: c.start)
        if i >= len(in_order):
            break
        prev, cur = in_order[i - 1], in_order[i]
        if cur.key in fixed_keys or cur.channel_id == prev.channel_id:
            continue
        nxt = in_order[i + 1] if i + 1 < len(in_order) else None
        used = {c.series_key for c in in_order if c is not cur}
        spent = sum(c.minutes for c in chosen) - cur.minutes
        alts = [
            a
            for a in pool
            if a.channel_id == prev.channel_id
            and a not in chosen
            and a.start >= prev.end
            and (nxt is None or a.end <= nxt.start)
            and a.series_key not in used
            and spent + a.minutes <= max(d.budget_left, 0)
        ]
        bonus = lambda a: a.base_weight + config.CHANNEL_STAY_BONUS * min(a.minutes, config.LENGTH_CAP_MIN)
        alt = min(alts, key=lambda a: (-bonus(a), a.start, a.key), default=None)
        if alt is None or bonus(alt) <= cur.base_weight:
            continue
        trial = [alt if c is cur else c for c in chosen]
        before, after = _violations(chosen, fixed, d).count(), _violations(trial, fixed, d).count()
        if after[0] <= before[0] and after[1] <= before[1]:
            d.dropped[cur.key] = CHANNEL
            chosen = trial
    return sorted(chosen, key=lambda c: c.start)


def _record_unchosen(pool: list[Candidate], chosen: list[Candidate], fixed, d: _Day) -> None:
    """후보였는데 안 들어간 방송의 이유: 조건을 하나씩 끈 배치와 비교해서 정한다.
    - 시간 예산·다양성 둘 다 없어도 못 들어감 → 겹침
    - 예산만 지킨 배치엔 있음(다양성 때문) → 다양성 / 다양성 감점만 둔 배치엔 있음(예산 때문) → 시간 상한 / 그 외 → 둘 다"""
    final = {c.key for c in chosen}
    factors = {id(c): c.factor for c in pool}
    for c in pool:
        c.factor = 1.0
    free = {c.key for c in select_best(pool)}
    budget_only = {c.key for c in select_best(pool, max(d.budget_left, 0))}
    for c in pool:
        c.factor = factors[id(c)]
    diversity_only = {c.key for c in select_best(pool)}
    for c in pool:
        if c.key in final or c.key in d.dropped:
            continue
        if c.key not in free:
            d.dropped[c.key] = OVERLAP
        elif c.key in budget_only and c.key not in diversity_only:
            d.dropped[c.key] = DIVERSITY
        elif c.key in diversity_only and c.key not in budget_only:
            d.dropped[c.key] = BUDGET
        else:
            d.dropped[c.key] = BUDGET_AND_DIVERSITY


def _entry(c: Candidate, role: str) -> Entry:
    p, s = c.payload
    return Entry(p.id, p.channel_id, p.title, p.start, p.end, s.score, "pick", scored=s, source=p, role=role)
