"""기준표 판정 (QUALITY.md): 하루표 하나를 M1~M7(반드시)·S1~S9(목표)로 검사하고 가치 지표를 잰다.

엔진이 남긴 기록(Plan.notes)은 "왜 못 지켰는지" 설명에만 쓰고, 통과 여부는 하루표 칸을 직접 보고 판정한다.
check_plan() 은 하루표를 세 번 짠다: 원래대로 / 입력 순서를 뒤집어서(M6) / LG 콘텐츠 없이(M7).
"""

import itertools
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..models.db import LgContent, Program, Senior
from . import config
from .breaks import in_break, parse_breaks
from .diversity import genre_cap, genre_minutes_share
from .gaps import first_high_moment
from .genres import genres_of, same_episode
from .plan import NOVELTY, PIN, REPRESENTATIVE, Entry, Plan
from .planner import build_plan, starts_in_day, wake_and_sleep
from .preference import Profile
from .rules import RuleSet
from .scoring import score_lg, score_program
from .tv_pattern import HIGH

TASTE_BASIS = ("series", "cast:", "genre:", "timeslot", "representative")


@dataclass
class Check:
    ok: bool | None  # None = 해당 없음
    detail: str = ""


@dataclass
class Report:
    must: dict[str, Check] = field(default_factory=dict)
    goals: dict[str, Check] = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)


def check_plan(
    programs: list[Program],
    lg_contents: list[LgContent],
    senior: Senior,
    profile: Profile,
    rules: RuleSet,
    day: date,
    numbered_channels: set[str] | None = None,
) -> tuple[Plan, Report]:
    """하루표를 짜고 기준표로 판정한다 (M6·M7 확인을 위해 두 번 더 짠다)."""
    nums = numbered_channels
    plan = build_plan(programs, lg_contents, senior, profile, rules, day, nums)
    again = build_plan(
        list(reversed(programs)), list(reversed(lg_contents)), senior, profile, rules, day, nums
    )
    no_lg = build_plan(programs, [], senior, profile, rules, day, nums)
    shape = lambda p: [(e.program_id, e.kind, e.start, e.end, e.reason) for e in p.entries]
    report = evaluate(
        plan,
        programs=programs,
        senior=senior,
        profile=profile,
        rules=rules,
        same_when_rebuilt=shape(plan) == shape(again),
        same_without_lg=[e.program_id for e in plan.picks()] == [e.program_id for e in no_lg.picks()],
        numbered_channels=nums,
    )
    return plan, report


def evaluate(
    plan: Plan,
    programs: list[Program],
    senior: Senior,
    profile: Profile,
    rules: RuleSet,
    same_when_rebuilt: bool = True,
    same_without_lg: bool = True,
    numbered_channels: set[str] | None = None,
) -> Report:
    day = plan.day or (plan.entries[0].start.date() if plan.entries else date.today())
    wake, sleep = wake_and_sleep(senior, day)
    r = Report()
    r.must["M1"] = _no_overlap(plan.entries)
    r.must["M2"] = _rules_kept(plan, programs, senior, profile, rules, wake, sleep, numbered_channels)
    r.must["M3"] = _inside_hours(plan, wake, sleep, parse_breaks(senior))
    r.must["M4"] = _series_once(plan.entries)
    r.must["M5"] = _reasons_true(plan, senior, profile, rules)
    r.must["M6"] = Check(
        same_when_rebuilt, "" if same_when_rebuilt else "입력 순서만 바꿨는데 하루표가 달라짐"
    )
    r.must["M7"] = Check(same_without_lg, "" if same_without_lg else "LG 콘텐츠 때문에 방송 칸이 바뀜")
    r.must["M8"] = _numbered(plan, numbered_channels)

    r.goals["S1"] = _representative(plan)
    r.goals["S2"] = _genre_share(plan, profile)
    r.goals["S3"] = _budget(plan)
    r.goals["S9"] = _lg(plan, profile)
    r.goals["S10"] = _lg_count(plan)
    r.goals["S8"] = Check(True, f"채널 전환 {_switches(plan.entries)}번")
    r.goals["S4"] = _streak(plan)
    r.goals["S5"] = _novelty(plan)
    r.goals["S6"] = _first_slot(plan, wake, sleep, profile)
    r.metrics = metrics(plan)
    return r


# ───────── 반드시 ─────────


def _no_overlap(entries: list[Entry]) -> Check:
    for a, b in itertools.pairwise(entries):
        if b.start < a.start:
            return Check(False, f"시간 순이 아님: {a.title} → {b.title}")
        if b.start < a.end:
            return Check(False, f"겹침: {a.title} · {b.title}")
    return Check(True)


def _rules_kept(plan, programs, senior, profile, rules, wake, sleep, numbered=None) -> Check:
    for e in plan.entries:
        series = getattr(e.source, "series_key", None)
        if rules.blocks(series, genres_of(e.source)):
            return Check(False, f"'안 볼래' 위반: {e.title}")
        if not rules.allows_start(e.start):
            return Check(False, f"'오늘은 그만 볼래' 뒤에 시작: {e.title} {e.start:%H:%M}")
    # '챙겨 줘'는 엔진 함수를 다시 쓰지 않고 규칙대로 직접 확인: 빠진 pin 은 (같은 회차가 더 좋은 쪽으로 있거나)
    # (겹치는 pin 이 점수가 더 높을 때 — 같으면 이른 시작 → ID)만 허용
    family = senior.family_picks or []
    rank = lambda p: (-score_program(p, profile, family).score, p.start, p.id)
    pinned = [
        p
        for p in programs
        if rules.is_pinned(p.series_key)
        and starts_in_day(p, wake, sleep)
        and rules.allows_start(p.start)
        and not rules.blocks(p.series_key, genres_of(p))
        and (numbered is None or p.channel_id in numbered)  # 채널 번호 없는 방송은 넣지 않음 (M8 이 먼저)
        and not in_break(p.start, parse_breaks(senior))  # 고정 비움 시간 시작도 넣지 않음 (M3 가 먼저)
    ]
    planned = {e.program_id for e in plan.entries}
    in_plan = [p for p in pinned if p.id in planned]
    for p in pinned:
        if p.id in planned:
            continue
        same_ep = any(same_episode(q, p) and rank(q) < rank(p) for q in in_plan)
        beaten = any(q.start < p.end and p.start < q.end and rank(q) < rank(p) for q in in_plan)
        if not (same_ep or beaten):
            return Check(False, f"'챙겨 줘' 빠짐: {p.title} {p.start:%H:%M}")
    return Check(True, f"챙겨 줘 {len(in_plan)}개 포함")


def _inside_hours(plan: Plan, wake, sleep, breaks=()) -> Check:
    for e in plan.entries:
        if in_break(e.start, list(breaks)):
            return Check(False, f"고정 비움 시간에 시작: {e.title} {e.start:%H:%M}")
        if not (wake <= e.start < sleep):
            return Check(False, f"기상~취침 밖 시작: {e.title} {e.start:%H:%M}")
        if e.role != PIN and e.start.hour not in plan.hours:
            return Check(False, f"시청 시간대 밖 시작: {e.title} {e.start:%H:%M}")
    return Check(True)


def _series_once(entries: list[Entry]) -> Check:
    """같은 회차 하루 1번 (회차를 모르면 같은 시리즈 1번 — genres.same_episode)."""
    seen: list = []
    for e in entries:
        if getattr(e.source, "series_key", None) is None:
            continue
        if any(same_episode(e.source, s) for s in seen):
            return Check(False, f"같은 회차 두 번: {e.title}")
        seen.append(e.source)
    return Check(True)


def _numbered(plan: Plan, numbered: set[str] | None) -> Check:
    """채널 번호가 없는 방송은 하루표에 없어야 함 (LG 콘텐츠는 상관없음)."""
    if numbered is None:
        return Check(None, "확인 안 함: 채널 번호표가 없음")
    bad = [e.title for e in plan.entries if isinstance(e.source, Program) and e.channel_id not in numbered]
    return Check(not bad, f"번호 없는 채널 방송: {', '.join(bad)}" if bad else "")


def _reasons_true(plan: Plan, senior: Senior, profile: Profile, rules: RuleSet) -> Check:
    for e in plan.entries:
        if not e.reason:
            return Check(False, f"이유 없음: {e.title}")
        bad = [b for b in e.basis.split("+") if not _basis_holds(b, e, plan, senior, profile, rules)]
        if bad:
            return Check(False, f"이유와 근거가 다름: {e.title} — {e.reason} ({bad[0]})")
    return Check(True)


def _basis_holds(b: str, e: Entry, plan: Plan, senior: Senior, profile: Profile, rules: RuleSet) -> bool:
    src = e.source
    series = getattr(src, "series_key", None)
    kind, _, arg = b.partition(":")
    checks = {
        "fill": lambda: e.kind == "fill",
        "series": lambda: profile.series.get(series, 0) > 0,
        "new": lambda: bool(getattr(src, "is_new", False)),
        "live": lambda: bool(getattr(src, "is_live", False)),
        "cast": lambda: arg in (src.cast or []) and profile.cast.get(arg, 0) > 0,
        "genre": lambda: arg in genres_of(src) and profile.genre.get(arg, 0) > 0,
        "timeslot": lambda: profile.timeslot_score(e.start) > 0,
        "more_episode": lambda: any(
            q.source.series_key == series and not same_episode(q.source, src) for q in plan.picks()
        ),
        "family": lambda: series in (senior.family_picks or []),
        "pin": lambda: rules.is_pinned(series),
        "representative": lambda: (
            bool(getattr(src, "is_new", False))
            and profile.series.get(series, 0) == max(profile.series.values(), default=0)
        ),
        "novelty": lambda: arg == src.genre and arg in config.NEAR_GENRES.get(plan.favorite_genre or "", []),
        "lg": lambda: arg in genres_of(src) and e.kind == "lg",
        "unknown_taste": lambda: not plan.knows_taste and bool(src.is_new or src.is_live),
        "background": lambda: profile.tier(e.start.hour) == HIGH,
        "none": lambda: True,
    }
    return kind in checks and checks[kind]()


# ───────── 목표 ─────────


def _representative(plan: Plan) -> Check:
    rep = plan.with_role(REPRESENTATIVE)
    if rep:
        return Check(True, f"{rep[0].title} {rep[0].start:%H:%M}")
    return Check(None, plan.notes.get("S1", "해당 없음"))


def _counted_for_share(plan: Plan) -> list[Entry]:
    """장르 비율에 세는 칸: 방송 칸 중 대표 방송·챙겨 줘 제외."""
    return [e for e in plan.picks() if e.role not in (REPRESENTATIVE, PIN)]


def _genre_share(plan: Plan, profile: Profile) -> Check:
    counted = _counted_for_share(plan)
    if len(counted) < config.GENRE_SHARE_MIN_COUNT:
        return Check(
            None, f"해당 없음: 대표 방송·챙겨 줘 말고 고른 방송이 {config.GENRE_SHARE_MIN_COUNT}개 미만"
        )
    shares = genre_minutes_share(counted)
    over = {g: s for g, s in shares.items() if s > genre_cap(g, profile) + 1e-9}
    detail = ", ".join(
        f"{g} {s:.0%}(상한 {genre_cap(g, profile):.0%})"
        for g, s in sorted(shares.items(), key=lambda kv: -kv[1])
    )
    if over:
        return Check(False, f"{detail} — {plan.notes.get('S2', '')}")
    return Check(True, detail)


def _budget(plan: Plan) -> Check:
    used = sum(e.minutes for e in plan.entries)  # 하루표 전체 (방송 + 채널 유지 + LG)
    lower = plan.budget_min * config.BUDGET_LOWER_RATIO
    detail = (
        f"{used}분 / 상한 {plan.budget_min:.0f}분 (하한 {lower:.0f}분{' — 짧음' if used < lower else ''})"
    )
    if used > plan.budget_min + 1e-9:
        return Check(False, f"{detail} — {plan.notes.get('S3', '')}")
    return Check(True, detail)


def _lg(plan: Plan, profile: Profile) -> Check:
    lgs = [e for e in plan.entries if e.kind == "lg"]
    total = sum(e.minutes for e in plan.entries)
    share = sum(e.minutes for e in lgs) / total if total else 0.0
    exempt = config.NOVELTY_LG_SKIPS_SCORE_RULE  # 새로 추천 LG 1개는 점수 기준 예외
    weak = [
        e.title
        for e in lgs
        if not (exempt and e.role == NOVELTY)
        and score_lg(e.source, profile, e.start).score < plan.floor * config.LG_SCORE_RATIO - 1e-9
    ]
    detail = f"LG {sum(e.minutes for e in lgs)}분 ({share:.0%}, 상한 {config.LG_SHARE_MAX:.0%})"
    if exempt and any(e.role == NOVELTY for e in lgs):
        detail += " · 새로 추천 LG 1개는 점수 기준 예외"
    if weak:
        return Check(False, f"{detail} — 취향 점수 미달: {', '.join(weak)}")
    if share > config.LG_SHARE_MAX + 1e-9:
        return Check(False, detail)
    return Check(True, detail)


def _lg_count(plan: Plan) -> Check:
    n_lg = sum(1 for e in plan.entries if e.kind == "lg")
    n_pick = len(plan.picks())
    detail = f"LG {n_lg}칸 / 방송 {n_pick}칸"
    return Check(n_lg < n_pick or n_lg == 0, detail)


def _switches(entries: list[Entry]) -> int:
    return sum(1 for a, b in itertools.pairwise(entries) if a.channel_id != b.channel_id)


def _streak(plan: Plan) -> Check:
    genres = [e.source.genre for e in plan.picks()]
    for i in range(len(genres) - config.STREAK_MAX):
        if len(set(genres[i : i + config.STREAK_MAX + 1])) == 1:
            return Check(False, f"{genres[i]} {config.STREAK_MAX + 1}연속 — {plan.notes.get('S4', '')}")
    return Check(True)


def _novelty(plan: Plan) -> Check:
    nov = plan.with_role(NOVELTY)
    if nov:
        return Check(True, f"{nov[0].source.genre} — {nov[0].title}")
    note = plan.notes.get("S5", "새로 추천할 방송이 없음")
    return Check(None if note.startswith("해당 없음") else False, note)


def _first_slot(plan: Plan, wake, sleep, profile: Profile) -> Check:
    """S6: 켜짐 '높음' 구간이 처음 시작되면 30분 안에 칸 (그때 이미 이어지고 있는 칸이어도 됨)."""
    moment = first_high_moment(wake, sleep, profile)
    if moment is None:
        return Check(None, "해당 없음: 켜짐 '높음' 시각이 없음")
    limit = moment + timedelta(minutes=config.FIRST_SLOT_WITHIN_MIN)
    hit = [e for e in plan.entries if e.start <= limit and e.end > moment]
    detail = f"'높음' 시작 {moment:%H:%M}" + (f", 칸 {hit[0].start:%H:%M}" if hit else "")
    return Check(bool(hit), detail if hit else f"{detail} — 30분 안에 칸 없음 (빈자리·LG 조건)")


# ───────── 가치 지표 ─────────


def metrics(plan: Plan) -> dict:
    entries = plan.entries
    total = sum(e.minutes for e in entries)
    lg_min = sum(e.minutes for e in entries if e.kind == "lg")
    taste = [e for e in entries if any(b.startswith(TASTE_BASIS) for b in e.basis.split("+"))]
    nov = plan.with_role(NOVELTY)
    share = lambda items: {g: round(s, 3) for g, s in genre_minutes_share(items).items()}
    return {
        "taste_match": round(len(taste) / len(entries), 3) if entries else 0.0,
        "new_genre": nov[0].source.genre if nov else None,
        "lg_minutes": lg_min,
        "lg_share": round(lg_min / total, 3) if total else 0.0,
        "genre_share_with_rep": share(plan.picks()),
        "genre_share_without_rep": share([e for e in plan.picks() if e.role != REPRESENTATIVE]),
        "switches": _switches(entries),
        "ask_interests": not plan.knows_taste,
        "rest_minutes": round(sum((b - a).total_seconds() / 60 for a, b in plan.rests)),
        "background_minutes": sum(e.minutes for e in entries if e.role == "background"),
    }
