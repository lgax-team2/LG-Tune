"""하루표 짜기: 오늘 편성 + 취향 + 규칙 → 하루표(Plan). 기준표는 QUALITY.md.

순서 (앞 단계가 우선 — 기준표 우선순위와 같음):
1. 후보 거르기: 기상~취침 사이 시작, "안 볼래"·"그만 볼래" 아님, 시청 시간대(TV 켜짐 '중간' 이상 시각) 안 ("챙겨 줘" 예외)
2. 먼저 넣기: "챙겨 줘"(pin) → 오늘의 대표 방송(S1). 넣은 시간만큼 하루 시간 예산에서 뺌
3. 배치(DP): 남은 예산 안에서 무게 합 최대 (selection.py). TV 켜짐 '높음' 시각부터 채우고 남은 예산으로 '중간' 시각.
   같은 시리즈는 무게가 가장 큰 회차 하나만 후보(M4)
4. 다양성(S2·S4): 넘친 장르의 가장 약한 칸·3연속 줄의 칸 무게를 깎아 다시 배치 (최대 MAX_REPLANS 번, 못 지키면 위반이 가장 적은 결과)
5. 채널 유지(S8): 앞 칸과 같은 채널에 거의 비슷한 방송이 있으면 그걸로 바꿈 (다른 기준을 해치지 않을 때만)
6. 새로 추천(S5): 남은 시간·빈자리에 들어가는 방송 1개 (없으면 7 에서 LG 콘텐츠로)
7. 빈 시간 채우기(gaps.py: 켜짐 높음=배경 편성 / 중간=짧게 / 낮음=쉬는 시간) → 8. 이유 붙이기(reason.py)
예산 두 개 (결정 D25): 방송(pick)은 집중 시청 상한(골라 본 시간 평균) 안에서, 하루 총 시간 상한(TV 켜짐 시간 평균)의
남은 만큼은 빈 시간 채우기(배경 편성·LG)에 쓴다.
하루표에 못 들어간 방송은 이유를 Plan.dropped 에, 못 지킨 목표는 Plan.notes 에 남긴다.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from ..models.db import LgContent, Program, Senior
from . import config
from .breaks import in_break, parse_breaks
from .diversity import genre_cap, genre_minutes_share, long_runs, over_share_genres, streak_breakers
from .gaps import fill_gaps, first_high_moment, first_viewing_moment
from .genres import genres_of, same_episode
from .novelty import novelty_choices, novelty_genres
from .plan import NORMAL, NOVELTY, PIN, REPRESENTATIVE, Entry, Plan
from .preference import Profile
from .reason import explain
from .rules import RuleSet
from .scoring import Scored, score_lg, score_program
from .selection import Candidate, overlaps, select_best
from .tv_pattern import HIGH

# 빠진 이유 (확인 화면 "빠진 방송")
OUT_OF_DAY = "기상 전·취침 후"
BY_RULE = "규칙으로 제외"
OFF_HOURS = "시청 시간대 밖"
GENRE_SWAP = "장르 상한 → 다른 장르 LG"
FIXED_BREAK = "고정 비움 시간"
PAUSED = "쉬어가는 중"
NO_NUMBER = "채널 번호 없음"
LEFT_ON = "켜 두는 방송"
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
    GENRE_SWAP,
    FIXED_BREAK,
    PAUSED,
    NO_NUMBER,
    LEFT_ON,
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


def in_viewing_hours(start: datetime, hours: set[int]) -> bool:
    """시청 시간대(Profile.viewing_hours — TV 켜짐 '중간' 이상인 시각)에 시작하는가."""
    return start.hour in hours


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
        if any(same_episode(k, p) or overlaps(p, k) for k in kept):
            continue
        kept.append(_candidate(p, s, 0.0))
    return sorted(kept, key=lambda c: c.start)


@dataclass
class _Day:
    """하루표를 짜는 동안 쓰는 값 묶음."""

    profile: Profile
    rules: RuleSet
    hours: set[int]
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
    numbered_channels: set[str] | None = None,
) -> Plan:
    """numbered_channels: 리모컨 채널 번호가 있는 채널 (None 이면 확인 안 함). 번호 없는 채널 방송은 넣지 않음 (M8)."""
    programs = sorted(programs, key=lambda p: (p.start, p.channel_id, p.id))  # 같은 입력 → 같은 결과 (M6)
    lg_contents = sorted(lg_contents, key=lambda c: c.id)
    wake, sleep = wake_and_sleep(senior, day)
    breaks = parse_breaks(senior)
    hours = profile.viewing_hours()
    knows_taste = profile.knows_taste
    family = senior.family_picks or []
    scored = [(p, score_program(p, profile, family)) for p in programs]
    dropped: dict[str, str] = {}

    # 1) 후보 거르기
    usable = []  # 기상~취침, 규칙 통과 (채널 유지 칸에도 씀)
    for p, s in scored:
        if numbered_channels is not None and p.channel_id not in numbered_channels:
            dropped[p.id] = NO_NUMBER
        elif not starts_in_day(p, wake, sleep):
            dropped[p.id] = OUT_OF_DAY
        elif not rules.allows_start(p.start) or rules.blocks(p.series_key, genres_of(p)):
            dropped[p.id] = BY_RULE
        elif in_break(p.start, breaks):
            dropped[p.id] = FIXED_BREAK
        elif p.series_key in profile.paused and not rules.is_pinned(p.series_key):
            dropped[p.id] = PAUSED  # 반복 거절 → 쉬어가기 (방송·채우기 모두 안 넣음)
        else:
            usable.append((p, s))
    eligible = []  # 점수로 고를 수 있는 방송: 시청 시간대 안 (+ 취향을 모르면 새 회차·생방송만)
    for p, s in usable:
        if rules.is_pinned(p.series_key):
            continue
        if not in_viewing_hours(p.start, hours):
            dropped[p.id] = OFF_HOURS
        elif p.series_key in profile.left_on_series:  # 틀어만 놓던 방송 → 집중 시청 말고 배경 편성 후보 (D24)
            dropped[p.id] = LEFT_ON
        elif not knows_taste and not (p.is_new or p.is_live):
            dropped[p.id] = NO_TASTE
        else:
            eligible.append((p, s))
    floor = candidate_floor([s.score for _, s in eligible])
    focus = profile.daily_budget_min if profile.focus_budget_min is None else profile.focus_budget_min
    d = _Day(
        profile, rules, hours, floor, min(focus, profile.daily_budget_min), dropped, {}
    )  # 방송은 집중 시청 상한 안에서

    # 2) 먼저 넣기: 챙겨 줘 → 대표 방송
    fixed: list[tuple[Candidate, str]] = [(c, PIN) for c in resolve_pins(usable, rules)]
    kept_pins = {c.key for c, _ in fixed}
    for p, _ in usable:
        if rules.is_pinned(p.series_key) and p.id not in kept_pins:
            same = any(same_episode(c, p) for c, _ in fixed)
            dropped[p.id] = SAME_SERIES if same else PIN_CLASH
    rep = _representative(eligible, fixed, d)
    if rep:
        fixed.append((rep, REPRESENTATIVE))
    d.budget_left -= sum(c.minutes for c, _ in fixed)
    if d.budget_left < 0:
        d.notes["S3"] = "대표 방송·챙겨 줘만으로 집중 시청 상한을 넘음 (우선순위가 더 높음)"
    open_cands = _open_candidates(eligible, fixed, d)

    # 3)~5) 배치 + 다양성 + 채널 유지
    pool = _one_per_series(_above_floor(open_cands, d), d)
    chosen = _place_with_diversity(pool, fixed, d)
    chosen = _prefer_same_channel(chosen, pool, fixed, d)
    _record_unchosen(pool, chosen, fixed, d)
    chosen, swapped = _swap_over_cap(
        chosen, fixed, d
    )  # 그래도 장르 상한을 넘으면 그 칸은 다른 장르 LG 자리로

    # 6) 새로 추천: 남은 시간·빈자리에 들어가는 방송 (우선순위가 낮아 배치가 끝난 뒤에)
    novel_genres = novelty_genres(profile, rules)
    if not knows_taste:
        d.notes["S5"] = "해당 없음: 아직 취향을 몰라 가까운 장르를 정할 수 없음"
    elif not novel_genres:
        d.notes["S5"] = "해당 없음: 가장 좋아하는 장르와 가까운 장르 중 아직 안 본 장르가 없음"
    taken = [c for c, _ in fixed] + chosen
    room = d.budget_left - sum(c.minutes for c in chosen)
    free = [
        c
        for c in open_cands
        if c not in chosen
        and not any(overlaps(c, t) for t in taken)
        and not any(same_episode(c, t) for t in taken)
    ]
    choices = novelty_choices(free, novel_genres, room)
    novel = _novelty_keeping_diversity(choices, chosen, fixed, d)
    if novel:
        fixed.append((novel, NOVELTY))
    elif (
        choices and "S5" not in d.notes
    ):  # 넣을 시간·자리는 있었는데 더 높은 목표 때문에 못 넣음 (시간이 없으면 LG 쪽에서 판정)
        d.notes["S5"] = "새로 추천할 방송을 넣으면 장르 비율·3연속(더 높은 목표)이 나빠짐"

    # 6) 빈 시간 → 7) 이유
    picks = sorted(
        [_entry(c, role) for c, role in fixed] + [_entry(c, NORMAL) for c in chosen], key=lambda e: e.start
    )
    need_lg_novelty = novel_genres if (knows_taste and not novel) else []
    preset_lg = _lg_for_swapped(swapped, lg_contents, picks, profile, rules, floor)
    filled = fill_gaps(
        picks,
        [p for p, _ in usable],
        lg_contents,
        profile,
        rules,
        first_viewing_moment(wake, sleep, hours),
        floor,
        need_lg_novelty,
        sleep,
        first_high_moment(wake, sleep, profile),
        breaks,
        preset_lg,
        {c.key for c, _ in swapped},
    )
    if filled.novelty_note and "S5" not in d.notes:
        d.notes["S5"] = filled.novelty_note
    entries = filled.entries
    favorite = profile.favorite_genre()
    for e in entries:
        r = explain(e, knows_taste, favorite)
        e.reason, e.basis = r.text, r.basis
    return Plan(
        entries=entries,
        floor=floor,
        budget_min=profile.daily_budget_min,
        hours=hours,
        knows_taste=knows_taste,
        favorite_genre=favorite,
        scores={p.id: s.score for p, s in scored},
        dropped={k: v for k, v in dropped.items() if k not in {e.program_id for e in entries}},
        notes=d.notes,
        day=day,
        rests=filled.rests,
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


def _swap_over_cap(
    chosen: list[Candidate], fixed: list[tuple[Candidate, str]], d: _Day
) -> tuple[list[Candidate], list[tuple[Candidate, str]]]:
    """(E2) 다시 배치로도 장르 상한(S2)을 못 맞추면, 넘기는 장르의 칸을 하나씩 뺀다 — 빼면 상한 안으로 들어오는 칸 중
    가장 약한 것 (없으면 그 장르의 가장 약한 칸). 뺀 자리는 다른 장르 LG 로 채운다 (_lg_for_swapped).
    LG 가 있든 없든 똑같이 빼므로 'LG 가 방송을 밀어낸 것'이 아님 (기준표 M7)."""
    swapped: list[tuple[Candidate, str]] = []
    if not config.SWAP_OVER_CAP_TO_LG:
        return chosen, swapped
    for _ in range(len(chosen)):
        over = _violations(chosen, fixed, d).over
        if not over:
            break
        g = over[0]
        counted = chosen + [c for c, role in fixed if role == NOVELTY]
        options = [c for c in chosen if c.genre == g]
        if not options:
            break

        def fixes(c: Candidate, counted=counted, g=g) -> bool:
            rest = [x for x in counted if x is not c]
            return genre_minutes_share(rest).get(g, 0.0) <= genre_cap(g, d.profile) + 1e-9

        target = min(
            [c for c in options if fixes(c)] or options, key=lambda c: (c.base_weight, c.start, c.key)
        )
        chosen = [c for c in chosen if c is not target]
        swapped.append((target, g))
        d.dropped[target.key] = GENRE_SWAP
    if swapped:
        d.notes["S2"] = "다시 배치해도 상한을 못 맞춰 넘기는 칸을 다른 장르 LG 자리로 바꿈"
    return chosen, swapped


def _lg_for_swapped(
    swapped: list[tuple[Candidate, str]],
    lg_contents: list[LgContent],
    picks: list[Entry],
    profile: Profile,
    rules: RuleSet,
    floor: float,
) -> list[Entry]:
    """뺀 칸 자리마다 다른 장르 LG 1개 (그 자리에 들어가는 길이, 취향 하한 = 기준점 × LG_SCORE_RATIO 이상, 점수 최고).
    LG 칸 수 < 방송 칸 수(S10)를 지킨다. 맞는 LG 가 없으면 그 자리는 빈 시간 채우기에 맡김."""
    out: list[Entry] = []
    used: set[str] = set()
    n_picks = len(picks)
    for c, g in sorted(swapped, key=lambda cg: cg[0].start):
        if len(out) + 1 >= n_picks:
            break
        fits = [
            (score_lg(lg, profile, c.start), lg)
            for lg in lg_contents
            if lg.genre != g
            and lg.id not in used
            and lg.duration_min <= c.minutes
            and not rules.blocks(None, genres_of(lg))
        ]
        fits = [(s, lg) for s, lg in fits if s.score >= floor * config.LG_SCORE_RATIO]
        if not fits:
            continue
        s, lg = max(fits, key=lambda x: (x[0].score, x[1].duration_min, x[1].id))
        used.add(lg.id)
        end = c.start + timedelta(minutes=lg.duration_min)
        out.append(Entry(lg.id, lg.source, lg.title, c.start, end, 0.0, "lg", scored=s, source=lg))
    return out


def _candidate(p: Program, s: Scored, floor: float) -> Candidate:
    return Candidate(
        p.id,
        p.start,
        p.end,
        s.score,
        floor=floor,
        genre=p.genre,
        series_key=p.series_key,
        episode=getattr(p, "episode", None),
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
    """먼저 넣은 칸과 겹치지 않고, 그 회차가 아직 안 나온 후보."""
    used = [c for c, _ in fixed]
    out = []
    for p, s in eligible:
        if p.id in {c.key for c, _ in fixed}:
            continue
        if any(same_episode(p, c) for c in used):
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
    """같은 회차는 무게가 가장 큰 방송 하나만 (같으면 이른 시작 → ID). 기준표 M4 — 회차를 모르면 같은 시리즈 하나."""
    kept: list[Candidate] = []
    for c in sorted(cands, key=lambda c: (-c.base_weight, c.start, c.key)):
        if any(same_episode(c, k) for k in kept):
            d.dropped[c.key] = SAME_SERIES
        else:
            kept.append(c)
    keep = {id(c) for c in kept}
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
    share_factor: dict[str, float] = {}  # 장르 비율(S2) 때문에 깎인 몫만 따로 (이게 많이 쌓이면 후보에서 뺌)
    best, best_rank, best_factors = [], None, {}
    first_count = None  # 감점 전 첫 배치의 '비율에 세는 칸' 수
    for _ in range(config.MAX_REPLANS):
        for c in pool:
            c.factor = key_factor.get(c.key, 1.0)
        # 장르 비율 때문에 많이 깎인 후보는 빼서 자리를 비움 (무게가 0 보다 크면 DP 가 예산이 남는 한 계속 넣으므로)
        alive = [c for c in pool if share_factor.get(c.key, 1.0) >= config.REPLAN_DROP_FACTOR]
        chosen = _staged(alive, max(d.budget_left, 0), d.profile)
        v = _violations(chosen, fixed, d)
        counted = len(chosen) + sum(1 for _, role in fixed if role == NOVELTY)
        first_count = counted if first_count is None else first_count
        over, runs = v.count()
        if first_count >= config.GENRE_SHARE_MIN_COUNT and counted < config.GENRE_SHARE_MIN_COUNT:
            over += 1  # 칸을 줄여 '비율 판정 안 함(3칸 미만)'으로 피한 것도 위반으로 셈
        rank = (over, runs, -sum(c.base_weight for c in chosen))
        if best_rank is None or rank < best_rank:
            best, best_rank, best_factors = chosen, rank, {c.key: c.factor for c in pool}
        if v.count() == (0, 0):
            break
        for g in v.over:
            weakest = min(
                (c for c in chosen if c.genre == g), key=lambda c: (c.weight, -_minute(c.start), c.key)
            )
            key_factor[weakest.key] = key_factor.get(weakest.key, 1.0) * config.REPLAN_PENALTY
            share_factor[weakest.key] = share_factor.get(weakest.key, 1.0) * config.REPLAN_PENALTY
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
    """S8 동점 규칙: 앞 칸과 채널이 다르면, 앞 칸 채널에서 같은 자리에 들어가는 후보 중 점수 차 0.1 이내인 것으로 바꾼다.
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
        used = [c for c in in_order if c is not cur]
        spent = sum(c.minutes for c in chosen) - cur.minutes
        alts = [
            a
            for a in pool
            if a.channel_id == prev.channel_id
            and a not in chosen
            and a.start >= prev.end
            and (nxt is None or a.end <= nxt.start)
            and not any(same_episode(a, u) for u in used)
            and spent + a.minutes <= max(d.budget_left, 0)
        ]
        alt = min(alts, key=lambda a: (-a.score, a.start, a.key), default=None)
        if alt is None or alt.score < cur.score - config.CHANNEL_TIE_SCORE:  # 점수 차 0.1 이내면 지금 채널
            continue
        trial = [alt if c is cur else c for c in chosen]
        before, after = _violations(chosen, fixed, d).count(), _violations(trial, fixed, d).count()
        if after[0] <= before[0] and after[1] <= before[1]:
            d.dropped[cur.key] = CHANNEL
            chosen = trial
    return sorted(chosen, key=lambda c: c.start)


def _staged(pool: list[Candidate], budget: float, profile: Profile) -> list[Candidate]:
    """시간 배분 (결정 D18·D23): TV 켜짐 '높음' 시각에 걸친 후보로 먼저 배치하고, 남은 예산으로 나머지.
    패턴을 모르면 한 번에 배치."""
    high = [c for c in pool if _touches_high(c, profile)]
    if not profile.pattern_known or not high:
        return select_best(pool, budget)
    first = select_best(high, budget)
    taken = first
    rest = [
        c
        for c in pool
        if not _touches_high(c, profile) and not any(same_episode(c, f) or overlaps(c, f) for f in taken)
    ]
    return sorted(first + select_best(rest, budget - sum(c.minutes for c in first)), key=lambda c: c.start)


def _touches_high(c: Candidate, profile: Profile) -> bool:
    """방송이 걸친 시각 중 하나라도 TV 켜짐 '높음'인가 (결정 D23)."""
    last = c.end - timedelta(minutes=1)
    last_hour = last.hour if last.date() == c.start.date() else 23
    return any(profile.tier(h) == HIGH for h in range(c.start.hour, last_hour + 1))


def _record_unchosen(pool: list[Candidate], chosen: list[Candidate], fixed, d: _Day) -> None:
    """후보였는데 안 들어간 방송의 이유: 조건을 하나씩 끈 배치와 비교해서 정한다.
    - 시간 예산·다양성 둘 다 없어도 못 들어감 → 겹침
    - 예산만 지킨 배치엔 있음(다양성 때문) → 다양성 / 다양성 감점만 둔 배치엔 있음(예산 때문) → 시간 상한 / 그 외 → 둘 다"""
    final = {c.key for c in chosen}
    factors = {id(c): c.factor for c in pool}
    for c in pool:
        c.factor = 1.0
    free = {c.key for c in select_best(pool)}
    budget_only = {c.key for c in _staged(pool, max(d.budget_left, 0), d.profile)}
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
