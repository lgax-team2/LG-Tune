"""무작위 검사 (E-eval): 시청 기록·편성표·설정을 무작위로 만들어 기준표 반드시(M1~M9)를 판정한다.

- hypothesis 로 예시 200개. 시드(SEED) 고정이라 테스트·보고·전후 비교 모두 매번 같은 예시 → 같은 결과 (기준표 M6 과 같은 뜻)
- 판정은 quality.check_plan 을 그대로 씀. 실패하면 hypothesis 가 가장 작은 예시로 줄여서 보여 준다
- 보고용: `cd backend && uv run python -m tests.test_engine_random [--n 2000]` → M 코드별 실패 개수 + 가장 작게 줄인 실패 예시
"""

import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta
from random import Random

from hypothesis import HealthCheck, find, given, seed, settings
from hypothesis import strategies as st
from hypothesis.errors import NoSuchExample

from app.engine import config
from app.engine.preference import build_profile
from app.engine.quality import Report, check_plan
from app.engine.rules import RuleSet
from app.models.db import LgContent, Program, Senior, UserRule, WatchLog

DAY = date(2026, 12, 1)
MUST = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"]
EXAMPLES = 200
SEED = 20261201  # 무작위 예시를 만드는 시드 (바꾸면 다른 200개)

NUMBERED = ["KBS1", "KBS2", "MBC", "SBS", "EBS1", "TVC"]

GENRES = sorted(config.NEAR_GENRES)
SERIES = [f"s{i}" for i in range(8)]
CAST = ["가수A", "가수B", "배우A", "배우B"]

RANDOM_SETTINGS = settings(
    max_examples=EXAMPLES,
    database=None,  # 지난 실패를 기억해 두지 않음 (매번 같은 결과)
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


def _at(minutes: int, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day) + timedelta(minutes=minutes)


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ───────── 무작위 입력 만들기 ─────────


@st.composite
def programs(draw) -> list[Program]:
    """그날 편성: 번호 있는 채널 1~4개 (+ 가끔 번호 없는 채널), 채널마다 첫 방송 시각부터 밤까지 빈틈없이
    이어지는 방송 (실제 편성표처럼). 10분 단위, 한 편 10~180분, 마지막 방송은 자정을 넘기도 함. 가끔 편성 없는 30분."""
    channels = draw(st.lists(st.sampled_from(NUMBERED), min_size=1, max_size=4, unique=True))
    out = []
    for ch in channels + (["NEW"] if draw(st.booleans()) else []):
        t = draw(st.integers(24, 60)) * 10  # 04:00~10:00 부터
        while t < 24 * 60:
            t += draw(st.sampled_from([0, 0, 0, 30]))  # 가끔 편성 없는 30분
            length = draw(st.integers(1, 18)) * 10
            genre = draw(st.sampled_from(GENRES))
            extra = draw(st.lists(st.sampled_from(GENRES), max_size=1))
            i = len(out)
            out.append(
                Program(
                    id=f"P{i}",
                    channel_id=ch,
                    title=f"방송{i}",
                    series_key=draw(st.sampled_from(SERIES)),
                    genre=genre,
                    genres=[genre, *(g for g in extra if g != genre)],
                    start=_at(t),
                    end=_at(t + length),
                    cast=draw(st.lists(st.sampled_from(CAST), max_size=2, unique=True)),
                    cast_roles={},
                    episode=draw(st.one_of(st.none(), st.sampled_from(["1", "2"]))),
                    is_new=draw(st.booleans()),
                    is_live=draw(st.booleans()),
                )
            )
            t += length
    return [p for p in out if p.start.date() == DAY]  # 그날 시작하는 방송만 (DB 에서 읽는 것과 같음)


@st.composite
def lg_contents(draw) -> list[LgContent]:
    return [
        LgContent(
            id=f"L{i}",
            title=f"LG{i}",
            genre=draw(st.sampled_from(GENRES)),
            cast=draw(st.lists(st.sampled_from(CAST), max_size=1)),
            duration_min=draw(st.sampled_from([10, 20, 30, 40, 60])),
            source="LG채널",
        )
        for i in range(draw(st.integers(0, 6)))
    ]


@st.composite
def seniors(draw) -> Senior:
    breaks = []
    for _ in range(draw(st.integers(0, 2))):
        a = draw(st.integers(12, 42)) * 30  # 06:00~21:00
        breaks.append(f"{_hhmm(a)}-{_hhmm(a + draw(st.sampled_from([30, 60])))}")
    return Senior(
        id="r",
        name="무작위",
        age=75,
        wake_time=_hhmm(draw(st.integers(8, 20)) * 30),  # 04:00~10:00
        sleep_time=_hhmm(draw(st.integers(40, 47)) * 30),  # 20:00~23:30
        pref_source=draw(st.sampled_from(["child", "none"])),
        seed_prefs={
            "series": draw(st.lists(st.sampled_from(SERIES), max_size=2, unique=True)),
            "cast": draw(st.lists(st.sampled_from(CAST), max_size=2, unique=True)),
            "genres": draw(st.lists(st.sampled_from(GENRES), max_size=3, unique=True)),
        },
        family_picks=draw(st.lists(st.sampled_from(SERIES), max_size=2, unique=True)),
        fixed_breaks=breaks,
    )


@st.composite
def _log(draw, days_ago: int | None = None, start_min: int | None = None, **fixed) -> WatchLog:
    """시청 기록 한 건. 고정하지 않은 칸은 무작위 (5분 미만·취소·거절도 섞임)."""
    genre = fixed.get("genre") or draw(st.sampled_from(GENRES))
    days_ago = days_ago if days_ago is not None else draw(st.integers(1, 20))
    start_min = start_min if start_min is not None else draw(st.integers(0, 47)) * 30
    return WatchLog(
        senior_id="r",
        channel_id=fixed.get("channel_id") or draw(st.sampled_from(NUMBERED)),
        series_key=fixed.get("series_key") or draw(st.sampled_from(SERIES)),
        genre=genre,
        genres=[genre],
        cast=fixed.get("cast") or draw(st.lists(st.sampled_from(CAST), max_size=2, unique=True)),
        started_at=_at(start_min, DAY - timedelta(days=days_ago)),
        watched_min=float(fixed.get("watched_min") or draw(st.integers(1, 180))),
        feedback="none",
        how_started=fixed.get("how_started") or draw(st.sampled_from(sorted(config.SIGNAL))),
        cancelled=fixed["cancelled"] if "cancelled" in fixed else draw(st.booleans()),
        end_reason=draw(st.sampled_from([None, *sorted(config.END_REASON_WEIGHT)])),
    )


@st.composite
def watch_logs(draw) -> list[WatchLog]:
    """지난 0~20일의 시청 기록: 매일(또는 며칠마다) 같은 시각에 보는 습관 0~4개 + 아무 때나 본 기록 0~15개.
    습관이 있어야 TV 켜짐 패턴('높음'·'중간')이 생겨 빈 시간 채우기·LG·S6 까지 검사된다."""
    days = draw(st.integers(0, 20))
    out = []
    for _ in range(draw(st.integers(0, 4))):
        habit = {
            "series_key": draw(st.sampled_from(SERIES)),
            "genre": draw(st.sampled_from(GENRES)),
            "channel_id": draw(st.sampled_from(NUMBERED)),
            "cast": draw(st.lists(st.sampled_from(CAST), min_size=1, max_size=2, unique=True)),
            "watched_min": draw(st.integers(1, 18)) * 10,
            "how_started": draw(st.sampled_from(sorted(config.SIGNAL))),
            "cancelled": False,
        }
        start_min, every = draw(st.integers(10, 46)) * 30, draw(st.integers(1, 3))  # 05:00~23:00, n 일마다
        out += [draw(_log(d, start_min, **habit)) for d in range(1, days + 1) if d % every == 0]
    out += draw(st.lists(_log(), max_size=15))
    return sorted(out, key=lambda w: w.started_at)


@st.composite
def user_rules(draw) -> list[UserRule]:
    out = []
    for _ in range(draw(st.integers(0, 4))):
        kind = draw(st.sampled_from(["exclude", "pin", "skip_today", "rest_day"]))
        rule = UserRule(senior_id="r", kind=kind, target_type="series", target="", active=True)
        if kind == "exclude" and draw(st.booleans()):
            rule.target_type, rule.target = "genre", draw(st.sampled_from(GENRES))
        elif kind == "rest_day":
            rule.target_type, rule.date = "none", DAY.isoformat()
            rule.from_time = _hhmm(draw(st.integers(12, 46)) * 30)
        else:
            rule.target = draw(st.sampled_from(SERIES))
            rule.date = DAY.isoformat() if kind == "skip_today" else None
        out.append(rule)
    return out


@st.composite
def day_cases(draw) -> dict:
    return {
        "programs": draw(programs()),
        "lgs": draw(lg_contents()),
        "senior": draw(seniors()),
        "logs": draw(watch_logs()),
        "rules": draw(user_rules()),
    }


# ───────── 판정 ─────────


def run_case(case: dict) -> Report:
    rules = case["rules"]
    profile = build_profile(case["logs"], case["senior"], DAY, rules)
    _, report = check_plan(
        case["programs"],
        case["lgs"],
        case["senior"],
        profile,
        RuleSet(rules, DAY, case["senior"].wake_time),
        DAY,
        set(NUMBERED),
    )
    return report


def failed_must(report: Report) -> dict[str, str]:
    return {c: report.must[c].detail for c in MUST if report.must[c].ok is False}


def on_random_days(fn: Callable[[dict], None], n: int = EXAMPLES) -> Callable[[], None]:
    """fn(case) 를 무작위 예시 n개(기본 200)로 돌리는 함수로 (같은 시드 → 어디서 불러도 같은 예시)."""
    return seed(SEED)(settings(RANDOM_SETTINGS, max_examples=n)(given(day_cases())(fn)))


@on_random_days
def test_random_days_pass_every_must_rule(case):
    assert not failed_must(run_case(case))


# ───────── 보고용 (pytest 에서는 안 돎) ─────────


def count_failures(n: int = EXAMPLES) -> dict[str, int]:
    """예시 n개(앞 200개는 테스트와 같은 예시) 중 M 코드별 실패 개수."""
    counts = dict.fromkeys(MUST, 0)

    def collect(case):
        for code in failed_must(run_case(case)):
            counts[code] += 1

    on_random_days(collect, n)()
    return counts


def smallest_failure(code: str, n: int = EXAMPLES) -> tuple[dict, Report] | None:
    """그 M 코드를 어기는 예시 중 가장 작게 줄인 것 (없으면 None)."""
    try:
        case = find(
            day_cases(),
            lambda c: code in failed_must(run_case(c)),
            settings=settings(RANDOM_SETTINGS, max_examples=n),
            random=Random(SEED),
        )
    except NoSuchExample:
        return None
    return case, run_case(case)


def describe(case: dict) -> str:
    s = case["senior"]
    head = f"  어르신: 기상 {s.wake_time} 취침 {s.sleep_time} 관심사 {s.seed_prefs}"
    lines = [f"{head} 가족 {s.family_picks} 비움 {s.fixed_breaks}"]
    lines += [
        f"  방송 {p.id} {p.channel_id} {p.series_key} {p.genre} {p.start:%H:%M}~{p.end:%m-%d %H:%M} "
        f"회차={p.episode} 새={p.is_new} 생={p.is_live} 출연={p.cast}"
        for p in case["programs"]
    ]
    lines += [f"  LG {c.id} {c.genre} {c.duration_min}분 출연={c.cast}" for c in case["lgs"]]
    lines += [
        f"  기록 {w.started_at:%m-%d %H:%M} {w.series_key} {w.genre} {w.watched_min:.0f}분 "
        f"{w.how_started} {w.end_reason} 취소={w.cancelled}"
        for w in case["logs"]
    ]
    lines += [
        f"  규칙 {r.kind} {r.target_type}:{r.target} {r.date or ''} {r.from_time or ''}"
        for r in case["rules"]
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else EXAMPLES
    counts = count_failures(n)
    print(f"무작위 {n}개 중 M 실패 개수: {counts}")
    for code in MUST:
        found = smallest_failure(code, n) if counts[code] else None
        if found is None:
            print(f"\n{code}: 실패 예시 없음")
            continue
        case, report = found
        print(f"\n{code}: {report.must[code].detail}\n{describe(case)}")
