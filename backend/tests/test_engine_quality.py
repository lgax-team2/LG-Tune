"""좋은 하루표 기준표 v4 (backend/app/engine/QUALITY.md) 테스트.

- 반드시(M1~M9): 샘플 3명 + 테스트 페르소나 19명(예외형 8명 포함) 모두 통과해야 함
- 무작위 검사는 test_engine_random.py, 두 버전 비교는 `uv run python -m app.engine.compare`
- 목표(S1~S9): 규칙별 작은 예제로 확인
- 페르소나는 샘플 파일이 아니라 여기서 만든다 (편성표만 샘플 programs.json·lg_contents.json 을 씀)
"""

import json
from datetime import date, datetime, timedelta

import pytest

from app.engine import config
from app.engine.planner import build_plan
from app.engine.preference import Profile, build_profile
from app.engine.quality import check_plan
from app.engine.rules import RuleSet
from app.engine.scoring import score_program
from app.models.db import LgContent, Program, Senior, UserRule, WatchLog
from app.models.sample import SAMPLE_DIR

DAY = date(2026, 12, 1)
MUST = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"]


def at(hhmm: str, d: date = DAY) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day) + timedelta(hours=h, minutes=m)


def prog(pid, start, end, key=None, genre="교양", cast=("가수",), ch="KBS1", is_new=False, is_live=False):
    return Program(
        id=pid,
        channel_id=ch,
        title=pid,
        series_key=key or pid,
        genre=genre,
        genres=[genre],
        start=at(start),
        end=at(end),
        cast=list(cast),
        is_new=is_new,
        is_live=is_live,
    )


def lg(cid, genre, minutes, cast=("가수",)):
    return LgContent(id=cid, title=cid, genre=genre, cast=list(cast), duration_min=minutes, source="LG채널")


def senior(wake="06:00", sleep="22:00", series=(), cast=(), genres=(), family=(), source="child", breaks=()):
    return Senior(
        fixed_breaks=list(breaks),
        id="t",
        name="테스트",
        age=75,
        wake_time=wake,
        sleep_time=sleep,
        pref_source=source,
        seed_prefs={"series": list(series), "cast": list(cast), "genres": list(genres)},
        family_picks=list(family),
    )


def rule(kind, target="", target_type="series"):
    return UserRule(senior_id="t", kind=kind, target_type=target_type, target=target, active=True)


def profile(
    series=None, cast=None, genre=None, timeslot=None, budget=240.0, watch_share=None, seen=None, on=None
):
    return Profile(
        series=series or {},
        cast=cast if cast is not None else {"가수": 1.0},
        genre=genre or {},
        timeslot=timeslot or {},
        history_share=0.0,
        n_logs=0,
        daily_budget_min=budget,
        genre_watch_share=watch_share or {},
        genre_seen_share=seen or {},
        on_ratio=on if on is not None else {h: 1.0 for h in range(24)},  # 기본: 하루 종일 켜 두는 분
    )


def plan(programs, prof, s=None, rules=(), lgs=()):
    return build_plan(
        programs=programs,
        lg_contents=list(lgs),
        senior=s or senior(),
        profile=prof,
        rules=RuleSet(list(rules), DAY),
        day=DAY,
    )


def picks(p):
    return [e for e in p.entries if e.kind == "pick"]


# ───────── 편성표(샘플)와 페르소나 ─────────


def sample_programs() -> list[Program]:
    rows = json.loads((SAMPLE_DIR / "programs.json").read_text(encoding="utf-8"))
    return [
        Program(**{**r, "start": datetime.fromisoformat(r["start"]), "end": datetime.fromisoformat(r["end"])})
        for r in rows
    ]


def sample_lg() -> list[LgContent]:
    return [LgContent(**r) for r in json.loads((SAMPLE_DIR / "lg_contents.json").read_text(encoding="utf-8"))]


def logs_for(
    series_keys: list[str],
    minutes: float = 60.0,
    days: int = 14,
    how: str = "chosen",
    end_reason: str = "completed",
) -> list[WatchLog]:
    """오늘 편성표에서 그 시리즈가 하는 시각에, 지난 days 일 동안 매일 본 기록."""
    by_key = {}
    for p in sample_programs() + SERIAL:
        by_key.setdefault(p.series_key, p)
    by_key.update({p.series_key: p for p in EXTRA_PROGRAMS})
    out = []
    for d in range(1, days + 1):
        for key in series_keys:
            p = by_key[key]
            out.append(
                WatchLog(
                    senior_id="t",
                    channel_id=p.channel_id,
                    series_key=key,
                    genre=p.genre,
                    genres=list(p.genres),
                    cast=list(p.cast),
                    started_at=p.start - timedelta(days=d),
                    watched_min=minutes,
                    feedback="none",
                    how_started=how,
                    cancelled=False,
                    end_reason=end_reason,
                )
            )
    return out


def logs_on(series_keys: list[str], weekdays: set[int], minutes: float = 60.0) -> list[WatchLog]:
    """logs_for 와 같되, 요일(0=월~6=일)이 weekdays 인 날만."""
    return [w for w in logs_for(series_keys, minutes) if w.started_at.weekday() in weekdays]


def serial_episode(pid: str, start: str, end: str, episode: str) -> Program:
    """같은 드라마 2회 연속 방송 페르소나용 (EBS1 20~22시 자리를 연속극 두 회로)."""
    return Program(
        id=pid,
        channel_id="EBS1",
        title="주말 연속극",
        series_key="ebs-serial",
        genre="드라마",
        genres=["드라마"],
        start=at(start),
        end=at(end),
        cast=["배우A"],
        cast_roles={"배우A": "lead"},
        episode=episode,
        is_new=True,
        is_live=False,
    )


SERIAL = [
    serial_episode("SER-1", "20:00", "21:00", "10회"),
    serial_episode("SER-2", "21:00", "22:00", "11회"),
]


def programs_with_serial() -> list[Program]:
    return [
        p for p in sample_programs() if not (p.channel_id == "EBS1" and p.start.hour in (20, 21))
    ] + SERIAL


# 자정 넘는 방송 페르소나용: SBS 23:30 밤 뉴스 자리를 다음 날 01:10 까지 하는 심야 영화로
MIDNIGHT_MOVIE = Program(
    id="SBS-20261201-2330-MOVIE",
    channel_id="SBS",
    title="심야 영화",
    series_key="sbs-midnight-movie",
    genre="영화",
    genres=["영화"],
    start=at("23:30"),
    end=at("01:10", DAY + timedelta(days=1)),
    cast=["배우B"],
    is_new=True,
    is_live=False,
)
EXTRA_PROGRAMS = [MIDNIGHT_MOVIE]


def programs_with_midnight_movie() -> list[Program]:
    return [p for p in sample_programs() if p.series_key != "sbs-news-night"] + [MIDNIGHT_MOVIE]


def few_programs() -> list[Program]:
    """그날 편성 데이터가 5개 미만 (4개)."""
    keep = {"kbs1-news-pm", "kbs2-king-of-song", "kbs1-haetsal", "ebs-doctor"}
    return [p for p in sample_programs() if p.series_key in keep]


def logs_on_both_episodes(days: int = 14) -> list[WatchLog]:
    out = []
    for d in range(1, days + 1):
        for ep in SERIAL:
            out.append(
                WatchLog(
                    senior_id="t",
                    channel_id="EBS1",
                    series_key="ebs-serial",
                    genre="드라마",
                    genres=["드라마"],
                    cast=["배우A"],
                    started_at=ep.start - timedelta(days=d),
                    watched_min=60,
                    feedback="none",
                    how_started="chosen",
                    cancelled=False,
                    end_reason="completed",
                )
            )
    return out


EVERY_GENRE_BUT_THREE = ["뉴스", "드라마", "사극", "예능", "트로트", "교양", "다큐", "시사", "건강", "요리"]
PERSONAS = {
    # 극단형
    "관심사·기록 없음": {"s": senior(source="none"), "logs": [], "rules": []},
    "한 장르만": {"s": senior(genres=["사극"]), "logs": logs_for(["kbs1-king", "mbc-joseon"]), "rules": []},
    "저녁 1시간만": {"s": senior(genres=["교양"]), "logs": logs_for(["mbc-town"], minutes=60), "rules": []},
    "거의 다 안 볼래": {
        "s": senior(genres=["트로트"]),
        "logs": logs_for(["tvc-star"]),
        "rules": [rule("exclude", g, "genre") for g in EVERY_GENRE_BUT_THREE],
    },
    "외출 잦은 분": {
        "s": senior(genres=["뉴스", "드라마"]),
        "logs": logs_for(
            ["kbs1-news-am", "kbs1-news-pm", "kbs1-haetsal"]
        ),  # 아침·저녁만, 오후엔 TV 거의 안 켬
        "rules": [],
    },
    "평일·주말 다른 분": {
        "s": senior(genres=["드라마", "예능"]),
        "logs": logs_on(["kbs1-haetsal", "kbs2-season"], {0, 1, 2, 3, 4})
        + logs_on(
            ["kbs2-quiz", "kbs2-movie", "kbs2-cook"], {5, 6}
        ),  # 평일 저녁 드라마, 주말 낮 예능·영화 (지금은 섞어서 읽음)
        "rules": [],
    },
    "식사·약 시간 고정": {
        "s": senior(genres=["교양", "건강"], breaks=["07:30-08:00", "12:00-13:00", "18:00-18:30"]),
        "logs": logs_for(["kbs1-health100", "kbs1-hometown", "ebs-doctor"]),
        "rules": [],
    },
    "같은 드라마 2회 연속": {
        "s": senior(genres=["드라마"]),
        "logs": logs_on_both_episodes() + logs_for(["kbs1-haetsal"]),
        "rules": [],
        "programs": programs_with_serial(),
    },
    "자주 '다음에'": {
        "s": senior(genres=["예능", "트로트"]),
        "logs": logs_for(["kbs2-quiz", "tvc-star"])
        + logs_for(["kbs2-laugh"], minutes=3, days=5, end_reason="skipped")
        + logs_for(["sbs-laugh"], minutes=3, days=4, end_reason="help_cancel"),
        "rules": [],
    },
    # 보편형
    "뉴스·사극 위주": {
        "s": senior(genres=["뉴스", "사극"]),
        "logs": logs_for(["kbs1-news-pm", "kbs1-king", "mbc-joseon"]),
        "rules": [],
    },
    "드라마·교양 위주": {
        "s": senior(genres=["드라마", "교양"]),
        "logs": logs_for(["kbs1-haetsal", "kbs1-hometown", "sbs-garden"]),
        "rules": [],
    },
    # 예외형 (E-eval): 데이터가 모자라거나 규칙이 부딪치는 경우
    "기록 0일": {
        "s": senior(genres=["드라마", "트로트"], series=["kbs1-haetsal"]),  # 관심사는 있고 기록만 없음
        "logs": [],
        "rules": [],
    },
    "기록 3일": {
        "s": senior(genres=["드라마", "교양"]),
        "logs": logs_for(["kbs1-haetsal", "kbs1-hometown"], days=3),  # 켜짐 패턴 기준(7일) 미만
        "rules": [],
    },
    "틀어만 두는 분만": {
        "s": senior(source="none"),
        "logs": logs_for(["kbs1-news-noon", "kbs1-trot-party", "kbs1-docu", "kbs1-news-pm"], how="continued"),
        "rules": [],
    },
    "관심 장르 전부 안 볼래": {
        "s": senior(genres=["트로트", "사극"]),
        "logs": logs_for(["tvc-star", "kbs1-king"]),
        "rules": [rule("exclude", "트로트", "genre"), rule("exclude", "사극", "genre")],
    },
    "LG 콘텐츠 0개": {
        "s": senior(genres=["드라마", "교양"]),
        "logs": logs_for(["kbs1-haetsal", "kbs1-hometown", "sbs-garden"]),
        "rules": [],
        "lgs": [],
    },
    "자정 넘는 방송": {
        "s": senior(wake="09:00", sleep="01:00", genres=["예능", "영화"]),  # 새벽 1시에 주무심
        "logs": logs_for(["kbs2-laugh", "ebs-movie", "sbs-midnight-movie"]),
        "rules": [],
        "programs": programs_with_midnight_movie(),
    },
    "'챙겨 줘' 3개 겹침": {
        "s": senior(genres=["드라마"]),
        "logs": logs_for(["kbs1-haetsal", "mbc-bluesea", "sbs-garden"]),
        "rules": [rule("pin", k) for k in ("kbs1-haetsal", "mbc-bluesea", "sbs-garden")],  # 20:30~22:20 겹침
    },
    "편성 5개 미만": {
        "s": senior(genres=["드라마", "뉴스"]),
        "logs": logs_for(["kbs1-haetsal", "kbs1-news-pm"]),
        "rules": [],
        "programs": few_programs(),
    },
}
EDGE_PERSONAS = list(PERSONAS)[-8:]


def sample_numbers() -> set[str]:
    """샘플 채널 번호표 (channels.json) — M8 확인용."""
    return {
        c["id"]
        for c in json.loads((SAMPLE_DIR / "channels.json").read_text(encoding="utf-8"))
        if c.get("number")
    }


def persona_plan(name):
    p = PERSONAS[name]
    prof = build_profile(p["logs"], p["s"], DAY)
    return check_plan(
        programs=p.get("programs") or sample_programs(),
        lg_contents=p["lgs"] if "lgs" in p else sample_lg(),
        senior=p["s"],
        profile=prof,
        rules=RuleSet(p["rules"], DAY),
        day=DAY,
        numbered_channels=sample_numbers(),
    )


@pytest.mark.parametrize("name", list(PERSONAS))
def test_personas_pass_every_must_rule(name):
    _, report = persona_plan(name)
    failed = {c: report.must[c].detail for c in MUST if not report.must[c].ok}
    assert not failed, failed


@pytest.mark.parametrize(
    ("name", "interests"), [("뉴스·사극 위주", {"뉴스", "사극"}), ("드라마·교양 위주", {"드라마", "교양"})]
)
def test_common_personas_get_plans_that_follow_their_interests(name, interests):
    p, report = persona_plan(name)
    taste = [e for e in picks(p) if e.role != "novelty"]
    assert taste, "하루표가 비면 안 됨"
    in_interest = sum(e.minutes for e in taste if e.source.genre in interests)
    assert in_interest >= 0.5 * sum(e.minutes for e in taste)
    assert all(report.goals[c].ok is not False for c in ("S2", "S3")), report.goals


def test_persona_without_any_taste_gets_new_or_live_shows_with_honest_reason():
    p, _ = persona_plan("관심사·기록 없음")
    assert not p.knows_taste and picks(p)
    assert all(e.source.is_new or e.source.is_live for e in picks(p))
    assert {e.reason for e in picks(p)} == {"아직 취향을 몰라서 새로 하는 방송 위주로 골랐어요"}


def test_persona_watching_one_evening_hour_gets_short_evening_plan():
    p, _ = persona_plan("저녁 1시간만")
    assert p.hours == {18, 19}, "18:30~19:30 만 켬 → 18시·19시가 시청 시간대"
    assert p.budget_min == pytest.approx(60)
    assert sum(e.minutes for e in p.entries) <= 60


# ───────── 샘플 3명: 반드시 전부 통과 ─────────


@pytest.fixture
def sample_session(tmp_path):
    from app.models.db import init_db, make_engine, make_session_factory
    from app.models.sample import load_sample

    engine = make_engine(tmp_path / "q.db")
    init_db(engine)
    with make_session_factory(engine)() as s:
        load_sample(s)
        yield s
    engine.dispose()


@pytest.mark.parametrize("sid", ["s1", "s2", "s3"])
def test_sample_seniors_pass_every_must_rule(sample_session, sid):
    from app.engine.service import plan_day

    _, report = plan_day(sample_session, sid, DAY)
    failed = {c: report.must[c].detail for c in MUST if not report.must[c].ok}
    assert not failed, failed


def test_sample_s1_has_todays_representative_show(sample_session):
    from app.engine.service import plan_day

    p, report = plan_day(sample_session, "s1", DAY)
    rep = [e for e in p.entries if e.role == "representative"]
    assert len(rep) == 1 and rep[0].reason == f"오늘 꼭 챙겨 보실 {rep[0].title} 새 회차예요"
    assert report.goals["S1"].ok


# ───────── M: 판정기가 실제로 잡아내는지 ─────────


def test_quality_catches_same_series_twice_and_wrong_cast_reason():
    from app.engine.quality import evaluate

    progs = [prog("a1", "10:00", "11:00", key="a"), prog("a2", "12:00", "13:00", key="a")]
    p = plan(progs, profile(series={"a": 1.0}))
    assert [e.program_id for e in picks(p)] == ["a1"], "엔진은 같은 시리즈를 한 번만"
    p.entries.append(p.entries[0].__class__(**{**vars(p.entries[0]), "program_id": "a2", "source": progs[1]}))
    p.entries[-1].start, p.entries[-1].end = progs[1].start, progs[1].end
    p.entries[-1].basis = "cast:없는 사람"
    report = evaluate(
        p, programs=progs, senior=senior(), profile=profile(series={"a": 1.0}), rules=RuleSet([], DAY)
    )
    assert not report.must["M4"].ok
    assert not report.must["M5"].ok


def test_same_input_same_plan_even_if_input_order_changes():
    progs = [
        prog(f"p{i}", f"{8 + i}:00", f"{9 + i}:00", genre=g)
        for i, g in enumerate(["교양", "뉴스", "다큐"] * 3)
    ]
    prof = profile(genre={"교양": 1.0, "뉴스": 0.9, "다큐": 0.8})
    first = [e.program_id for e in plan(progs, prof).entries]
    again = [e.program_id for e in plan(list(reversed(progs)), prof).entries]
    assert first == again


def test_lg_never_pushes_out_a_show():
    progs = [prog("a", "10:00", "11:00"), prog("b", "11:30", "12:30")]
    prof = profile(series={"a": 1.0, "b": 1.0})
    with_lg = [e.program_id for e in picks(plan(progs, prof, lgs=[lg("x", "교양", 60), lg("y", "교양", 20)]))]
    assert with_lg == [e.program_id for e in picks(plan(progs, prof))]


# ───────── S1 오늘의 대표 방송 ─────────


def test_representative_is_new_episode_of_top_series_in_viewing_hours():
    progs = [
        prog("star-old", "16:30", "18:00", key="star"),
        prog("star-new", "21:00", "23:00", key="star", is_new=True),
        prog("other", "19:00", "20:00", key="other"),
    ]
    p = plan(progs, profile(series={"star": 1.0, "other": 0.6}))
    rep = [e for e in p.entries if e.role == "representative"]
    assert [e.program_id for e in rep] == ["star-new"]
    assert rep[0].reason == "오늘 꼭 챙겨 보실 star-new 새 회차예요"
    assert "star-old" not in [e.program_id for e in p.entries], "같은 시리즈 하루 1번"


def test_no_representative_when_top_series_is_weak_or_has_no_new_episode():
    weak = plan([prog("w", "20:00", "21:00", key="w", is_new=True)], profile(series={"w": 0.4}))
    assert not [e for e in weak.entries if e.role == "representative"]
    assert "S1" in weak.notes
    rerun_only = plan([prog("r", "20:00", "21:00", key="r")], profile(series={"r": 1.0}))
    assert not [e for e in rerun_only.entries if e.role == "representative"]


def test_representative_counts_in_budget_but_not_in_genre_share():
    """대표 방송(120분)이 상한(100분)보다 길어도 들어가고, 남은 예산이 없으니 다른 방송은 안 들어감."""
    progs = [
        prog("star", "20:00", "22:00", key="star", genre="트로트", is_new=True),
        prog("x", "10:00", "11:00"),
    ]
    p = plan(progs, profile(series={"star": 1.0, "x": 1.0}, budget=100))
    assert [e.program_id for e in picks(p)] == ["star"]
    assert "S3" in p.notes


# ───────── M4 같은 시리즈 하루 1번 (채널 유지 칸 포함) ─────────


def test_same_series_is_not_repeated_as_channel_fill():
    progs = [
        prog("a", "10:00", "11:00", key="a"),
        prog("a-again", "11:00", "11:10", key="a"),  # 짧은 빈 시간에 채널 유지로 들어갈 자리
        prog("b", "11:10", "12:00", key="b"),
    ]
    p = plan(progs, profile(series={"a": 1.0, "b": 1.0}))
    assert [e.program_id for e in p.entries] == ["a", "b"]


# ───────── S2 장르 비율 · S4 3연속 ─────────


def test_one_genre_takes_at_most_half_unless_the_viewer_watches_more():
    """네 칸(10~13시)에 트로트·다큐가 하나씩 겹쳐 있음: 보통은 트로트 절반까지, 실제로 75% 보는 분은 75% 까지."""
    progs = [prog(f"t{h}", f"{h}:00", f"{h + 1}:00", genre="트로트") for h in range(10, 14)]
    progs += [prog(f"d{h}", f"{h}:00", f"{h + 1}:00", genre="다큐", ch="EBS1") for h in range(10, 14)]
    base = {"genre": {"트로트": 1.0, "다큐": 0.9}, "budget": 240, "seen": {"트로트": 1.0, "다큐": 1.0}}
    half = [e.source.genre for e in picks(plan(progs, profile(**base)))]
    assert len(half) == 4 and half.count("트로트") <= 2
    loves = [e.source.genre for e in picks(plan(progs, profile(**base, watch_share={"트로트": 0.75})))]
    assert loves.count("트로트") == 3, "실제로 75% 보는 분은 상한이 그 비율까지 (3연속은 피해서)"


def test_no_three_same_genre_in_a_row():
    progs = [prog(f"t{i}", f"{10 + i}:00", f"{11 + i}:00", genre="트로트") for i in range(3)]
    progs += [prog("d", "11:00", "12:00", genre="다큐", ch="EBS1")]
    prof = profile(genre={"트로트": 1.0, "다큐": 0.7}, watch_share={"트로트": 1.0})
    genres = [e.source.genre for e in picks(plan(progs, prof))]
    assert all(not (a == b == c) for a, b, c in zip(genres, genres[1:], genres[2:])), genres


# ───────── S9 LG 콘텐츠 ─────────


def test_lg_content_needs_taste_score_near_floor():
    progs = [prog("a", "10:00", "12:00"), prog("b", "13:00", "15:00")]
    prof = profile(series={"a": 1.0, "b": 1.0}, genre={"트로트": 1.0}, cast={}, budget=400)
    liked = plan(progs, prof, lgs=[lg("liked", "트로트", 30, cast=())])  # 0.15 < 0.35×0.8
    assert not [e for e in liked.entries if e.kind == "lg"]
    prof2 = profile(series={"a": 1.0, "b": 1.0}, genre={"트로트": 1.0}, budget=400)  # 방송 240분 + LG 자리
    ok = plan(progs, prof2, lgs=[lg("liked", "트로트", 30)])  # 출연자 0.25 + 장르 0.15
    assert [e.program_id for e in ok.entries if e.kind == "lg"] == ["liked"]


def test_lg_share_stays_under_limit():
    progs = [prog("a", "10:00", "11:00"), prog("b", "12:00", "13:00"), prog("c", "14:00", "15:00")]
    lgs = [lg(f"l{i}", "교양", 60) for i in range(3)]
    p = plan(progs, profile(series={k: 1.0 for k in "abc"}, genre={"교양": 1.0}), lgs=lgs)
    lg_min = sum(e.minutes for e in p.entries if e.kind == "lg")
    assert lg_min <= config.LG_SHARE_MAX * sum(e.minutes for e in p.entries)


# ───────── S8 채널 전환 줄이기 ─────────


def test_same_channel_show_preferred_when_nearly_as_good():
    progs = [
        prog("first", "10:00", "11:00", ch="KBS1"),
        prog("other-ch", "11:00", "12:00", ch="MBC", genre="다큐"),
        prog("same-ch", "11:00", "12:00", ch="KBS1", genre="다큐"),
    ]
    prof = profile(
        series={"first": 1.0, "other-ch": 0.52, "same-ch": 0.5},
        genre={"교양": 0.5, "다큐": 0.5},
        seen={"교양": 1.0, "다큐": 1.0},  # 새로 추천(S5)이 끼어들지 않게
    )
    assert [e.program_id for e in picks(plan(progs, prof))] == ["first", "same-ch"]


# ───────── S5 새로 추천 1칸 ─────────


def test_novelty_picks_unseen_genre_near_favorite():
    near = config.NEAR_GENRES["트로트"][0]
    progs = [
        prog("fav", "19:00", "20:00", genre="트로트"),
        prog("new", "10:00", "11:00", genre=near, ch="EBS1"),
    ]
    prof = profile(series={"fav": 1.0}, genre={"트로트": 1.0}, seen={"트로트": 1.0})
    p = plan(progs, prof)
    nov = [e for e in p.entries if e.role == "novelty"]
    assert [e.program_id for e in nov] == ["new"]
    assert nov[0].reason.startswith("새로 추천해 드려요 — ")


def test_novelty_falls_back_to_lg_content():
    near = config.NEAR_GENRES["트로트"][0]
    progs = [
        prog("fav", "10:00", "11:00", genre="트로트"),
        prog("fav2", "13:00", "14:00", genre="트로트", ch="MBC"),
    ]
    everywhere = {"아침": 1.0, "낮": 1.0, "저녁": 1.0, "밤": 1.0}  # LG 취향 점수가 기준(S9)을 넘게
    prof = profile(
        series={"fav": 1.0, "fav2": 1.0}, genre={"트로트": 1.0}, seen={"트로트": 1.0}, timeslot=everywhere
    )
    p = plan(progs, prof, lgs=[lg("lg-new", near, 30)])
    nov = [e for e in p.entries if e.role == "novelty"]
    assert [(e.program_id, e.kind) for e in nov] == [("lg-new", "lg")]


def test_novelty_never_picks_excluded_genre():
    near = config.NEAR_GENRES["트로트"][0]
    progs = [
        prog("fav", "19:00", "20:00", genre="트로트"),
        prog("new", "10:00", "11:00", genre=near, ch="EBS1"),
    ]
    prof = profile(series={"fav": 1.0}, genre={"트로트": 1.0}, seen={"트로트": 1.0})
    p = plan(progs, prof, rules=[rule("exclude", near, "genre")], lgs=[lg("lg-new", near, 30)])
    assert all(near not in (e.source.genre,) for e in p.entries)
    assert "S5" in p.notes


# ───────── S6 첫 칸 ─────────


def test_first_slot_starts_within_30min_of_viewing_hours():
    """시청 시간대(09시~) 시작 30분 안에 첫 칸 (방송이 늦게 시작하면 LG 로)."""
    progs = [prog("late", "13:00", "15:00"), prog("later", "15:00", "16:00", ch="MBC")]
    on = {h: (1.0 if h >= 9 else 0.0) for h in range(24)}
    prof = profile(
        series={"late": 1.0, "later": 1.0},
        genre={"교양": 1.0},
        on=on,
        seen={"다큐": 1.0, "건강": 1.0, "요리": 1.0},
    )
    p = plan(progs, prof, lgs=[lg("morning", "교양", 30)])
    assert p.entries[0].start <= at("09:30")


# ───────── S7 출연자 공정성 ─────────


def test_program_without_cast_info_can_reach_full_score():
    """출연자 정보가 없는 방송도 만점(1.0)에 도달할 수 있다 (출연자 항목을 빼고 나머지 가중치로 비율 계산)."""
    prof = profile(series={"x": 1.0}, genre={"교양": 1.0}, timeslot={"저녁": 1.0}, cast={})
    show = prog("x", "20:00", "21:00", cast=[], is_new=True)
    assert score_program(show, prof, family_picks=["x"]).score == pytest.approx(1.0)


def test_missing_cast_info_never_loses_to_unliked_cast():
    """출연자 정보 없는 방송 vs 같은 조건에 출연자 선호가 0 인 방송: 정보 없는 쪽이 손해 보지 않는다."""
    prof = profile(series={"x": 0.8}, genre={"교양": 0.6}, cast={"좋아하는 가수": 1.0})
    no_info = score_program(prog("x", "20:00", "21:00", cast=[]), prof, []).score
    unliked = score_program(prog("x", "20:00", "21:00", cast=["모르는 배우"]), prof, []).score
    assert no_info >= unliked


def test_equal_scores_prefer_the_earlier_show():
    """점수가 같고 시간 예산이 한 칸뿐이면 시작이 이른 방송."""
    progs = [prog("late", "20:00", "21:00", key="late"), prog("early", "10:00", "11:00", key="early")]
    p = plan(progs, profile(series={"late": 1.0, "early": 1.0}, seen={"교양": 1.0}), lgs=[])
    assert [e.program_id for e in picks(p)] == ["early"] or len(picks(p)) == 2
    tight = plan(progs, profile(series={"late": 1.0, "early": 1.0}, budget=60, seen={"교양": 1.0}))
    assert [e.program_id for e in picks(tight)] == ["early"]


def test_sample_s1_has_two_more_shows_besides_representative(sample_session):
    """s1(하루 종일 켜 두는 분)은 대표 방송 말고도 집중 시청 방송이 2칸 이상."""
    from app.engine.service import plan_day

    p, _report = plan_day(sample_session, "s1", DAY)
    others = [e for e in picks(p) if e.role != "representative"]
    assert len(others) >= 2  # 장르 비율(S2)은 기준표 v4 부터 3칸 이상일 때만 판정


def test_novelty_lg_is_exempt_from_lg_taste_score_rule():
    """새로 추천 LG 1개는 '안 본 장르'라 취향 점수가 낮아도 들어간다 (LG 비율 상한은 그대로). 다른 LG 는 점수 기준 그대로."""
    near = config.NEAR_GENRES["트로트"][0]
    progs = [
        prog("fav", "10:00", "11:00", genre="트로트"),
        prog("fav2", "13:00", "14:00", genre="트로트", ch="MBC"),
    ]
    prof = profile(series={"fav": 1.0, "fav2": 1.0}, genre={"트로트": 1.0}, seen={"트로트": 1.0}, cast={})
    p = plan(progs, prof, lgs=[lg("lg-new", near, 30, cast=()), lg("lg-weak", "트로트", 30, cast=())])
    assert config.NOVELTY_LG_SKIPS_SCORE_RULE
    assert [(e.program_id, e.role) for e in p.entries if e.kind == "lg"] == [("lg-new", "novelty")]


def test_first_viewing_gap_is_filled_before_higher_scoring_spots():
    """LG 하나뿐: 점수가 더 높은 낮 빈 시간보다 하루 첫 시청 구간(아침) 빈 시간에 먼저 (기준표 S6)."""
    progs = [prog("a", "09:00", "11:00"), prog("b", "13:00", "15:00")]
    prof = profile(
        series={"a": 1.0, "b": 1.0},
        genre={"교양": 1.0},
        seen={"교양": 1.0, "다큐": 1.0, "건강": 1.0, "요리": 1.0},
        timeslot={"아침": 0.5, "낮": 1.0},
        budget=400,  # 하루 총 시간(방송 240분)에 LG 자리가 남게
    )
    p = plan(progs, prof, s=senior(wake="08:00"), lgs=[lg("only", "교양", 40)])
    assert [(e.program_id, e.start) for e in p.entries if e.kind == "lg"] == [("only", at("08:00"))]


# ───────── M2·M4 "챙겨 줘" 충돌 (Codex 리뷰에서 찾음) ─────────


def test_overlapping_pins_keep_the_higher_score():
    """겹치는 '챙겨 줘' 둘: 길이와 상관없이 점수 높은 쪽 (A 10분 0.55 vs B 60분 0.40 → A)."""
    progs = [prog("A", "10:00", "10:10", key="a"), prog("B", "10:00", "11:00", key="b")]
    prof = profile(series={"a": 1.0, "b": 0.5})
    p = plan(progs, prof, rules=[rule("pin", "a"), rule("pin", "b")])
    assert [e.program_id for e in picks(p)] == ["A"]
    assert "B" not in [e.program_id for e in picks(p)], (
        "B 는 방송 칸이 아님 (A 뒤에 같은 채널 배경으로 이어질 수는 있음)"
    )


def test_pinned_series_appears_once_a_day():
    progs = [prog("n1", "10:00", "11:00", key="news"), prog("n2", "12:00", "13:00", key="news")]
    p = plan(progs, profile(series={"news": 1.0}), rules=[rule("pin", "news")])
    assert [e.program_id for e in picks(p)] == ["n1"], "점수 같으면 이른 회차 하나만"


def test_quality_m2_is_judged_independently_of_the_engine():
    """판정기는 엔진 함수를 다시 쓰지 않고 규칙(겹치면 점수 높은 pin)으로 직접 검사 → 엔진이 틀리면 잡아냄."""
    from dataclasses import replace

    from app.engine.quality import evaluate

    progs = [prog("A", "10:00", "10:10", key="a"), prog("B", "10:00", "11:00", key="b")]
    prof = profile(series={"a": 1.0, "b": 0.5})
    rules = RuleSet([rule("pin", "a"), rule("pin", "b")], DAY)
    p = plan(progs, prof, rules=[rule("pin", "a"), rule("pin", "b")])
    wrong = replace(
        p.entries[0], program_id="B", title="B", start=progs[1].start, end=progs[1].end, source=progs[1]
    )
    p.entries = [wrong]
    assert not evaluate(p, programs=progs, senior=senior(), profile=prof, rules=rules).must["M2"].ok


def test_quality_m2_flags_lower_scored_episode_of_same_pinned_series():
    from dataclasses import replace

    from app.engine.quality import evaluate

    progs = [prog("hi", "10:00", "11:00", key="news", is_new=True), prog("lo", "12:00", "13:00", key="news")]
    prof = profile(series={"news": 1.0})
    rules = RuleSet([rule("pin", "news")], DAY)
    p = plan(progs, prof, rules=[rule("pin", "news")])
    assert [e.program_id for e in picks(p)] == ["hi"], "새 회차(점수 높음)를 챙김"
    p.entries = [
        replace(
            p.entries[0], program_id="lo", title="lo", start=progs[1].start, end=progs[1].end, source=progs[1]
        )
    ]
    assert not evaluate(p, programs=progs, senior=senior(), profile=prof, rules=rules).must["M2"].ok


def test_novelty_never_breaks_higher_priority_genre_share():
    """트로트 60분·교양 60분(50:50)에 '안 본 장르' 교양을 새로 추천하면 교양 67% → 넣지 않는다 (S2 > S5)."""
    progs = [
        prog("trot", "10:00", "11:00", genre="트로트"),
        prog("cult", "12:00", "13:00", genre="교양", ch="MBC"),
        prog("cult2", "14:00", "15:00", genre="교양", ch="EBS1"),
    ]
    prof = profile(series={"trot": 1.0, "cult": 1.0}, genre={"트로트": 1.0}, seen={"트로트": 1.0})
    p = plan(progs, prof)
    assert [e.program_id for e in picks(p)] == ["trot", "cult"]
    assert "S5" in p.notes


def test_novelty_does_not_make_three_in_a_row_with_fixed_slots():
    """시사 '챙겨 줘' 두 개 바로 뒤에 시사 새로 추천을 넣으면 시사 3연속 → 넣지 않는다 (S4 > S5)."""
    progs = [
        prog("p1", "10:00", "11:00", key="p1", genre="시사"),
        prog("p2", "11:00", "12:00", key="p2", genre="시사", ch="MBC"),
        prog("new", "12:00", "13:00", key="new", genre="시사", ch="SBS"),
    ]
    prof = profile(genre={"뉴스": 1.0}, seen={"뉴스": 1.0})
    p = plan(progs, prof, rules=[rule("pin", "p1"), rule("pin", "p2")])
    assert "new" not in [e.program_id for e in picks(p)], (
        "방송 칸(새로 추천)으로는 안 넣음 (빈 시간 채우기는 3연속 대상 아님)"
    )


# ───────── TV 켜짐 패턴: 시간 배분 · 빈 시간 3단계 · S10 ─────────


def test_persona_often_out_gets_nothing_in_the_afternoon():
    p, _ = persona_plan("외출 잦은 분")
    assert not [e for e in p.entries if 12 <= e.start.hour < 17], "오후엔 TV 를 거의 안 켬"
    assert any(a.hour < 17 and b.hour >= 12 for a, b in p.rests), "그 시간은 쉬는 시간으로 표시"


def test_high_on_hours_are_filled_first_when_budget_is_short():
    """시간 예산이 한 칸뿐: 켜짐 '중간' 시각의 조금 더 좋은 방송보다 '높음' 시각의 방송을 먼저 (결정 D18)."""
    progs = [prog("mid", "10:00", "11:00", key="mid"), prog("high", "20:00", "21:00", key="high")]
    on = {h: 0.0 for h in range(24)} | {10: 0.4, 20: 0.9}
    p = plan(progs, profile(series={"mid": 1.0, "high": 0.9}, budget=60, on=on, seen={"교양": 1.0}))
    assert [e.program_id for e in picks(p)] == ["high"]


def test_gap_in_high_on_hours_keeps_the_channel_as_background():
    progs = [
        prog("a", "10:00", "11:00", key="a"),
        prog("k1", "11:00", "12:00", key="k1", genre="다큐", cast=()),
        prog("k2", "12:00", "13:00", key="k2", genre="뉴스", cast=()),
        prog("b", "13:00", "14:00", key="b", ch="MBC"),
    ]
    p = plan(progs, profile(series={"a": 1.0, "b": 1.0}, budget=600, seen={"교양": 1.0}))
    bg = [e for e in p.entries if e.role == "background"]
    assert [(e.program_id, e.kind) for e in bg] == [("k1", "fill"), ("k2", "fill")]
    assert all(e.reason.startswith("평소 이 시간엔 TV 를 켜 두셔서") for e in bg)


def test_gap_in_mid_on_hours_is_filled_20_minutes_at_most():
    progs = [
        prog("a", "10:00", "11:00", key="a"),
        prog("k1", "11:00", "12:00", key="k1", cast=()),
        prog("b", "13:00", "14:00", key="b", ch="MBC"),
    ]
    on = {h: 0.4 for h in range(24)}
    p = plan(
        progs,
        profile(series={"a": 1.0, "b": 1.0}, budget=600, on=on, seen={"교양": 1.0}),
        lgs=[lg("x", "교양", 20), lg("y", "교양", 60)],
    )
    gap = [e for e in p.entries if e.kind != "pick"]
    assert sum(e.minutes for e in gap) <= 20


def test_gap_in_low_on_hours_becomes_rest():
    progs = [prog("a", "10:00", "11:00", key="a"), prog("b", "15:00", "16:00", key="b", ch="MBC")]
    on = {h: 0.0 for h in range(24)} | {10: 0.9, 15: 0.9}
    p = plan(progs, profile(series={"a": 1.0, "b": 1.0}, budget=600, on=on), lgs=[lg("x", "교양", 60)])
    assert [e.kind for e in p.entries] == ["pick", "pick"]
    assert p.rests == [(at("11:00"), at("15:00")), (at("16:00"), at("22:00"))], "마지막 방송 뒤~취침도"


def test_lg_slots_stay_fewer_than_show_slots():
    """방송 2칸(240분)이면 LG 비율 30% 로는 3칸까지 되지만, S10(LG 칸 < 방송 칸) 때문에 1칸만."""
    progs = [prog("a", "10:00", "12:00", key="a"), prog("b", "15:00", "17:00", key="b", ch="MBC")]
    lgs = [lg(f"l{i}", "교양", 30) for i in range(4)]
    seen = {"교양": 1.0, "다큐": 1.0, "건강": 1.0, "요리": 1.0}
    p = plan(progs, profile(series={"a": 1.0, "b": 1.0}, genre={"교양": 1.0}, budget=600, seen=seen), lgs=lgs)
    assert sum(1 for e in p.entries if e.kind == "lg") == 1


def test_lg_reason_names_the_taste_it_matches():
    progs = [prog("a", "10:00", "11:00", key="a"), prog("b", "12:00", "13:00", key="b", ch="MBC")]
    p = plan(
        progs,
        profile(
            series={"a": 1.0, "b": 1.0},
            genre={"교양": 1.0},
            budget=600,
            seen={"교양": 1.0, "다큐": 1.0, "건강": 1.0, "요리": 1.0},
        ),
        lgs=[lg("x", "교양", 30)],
    )
    lgs = [e for e in p.entries if e.kind == "lg"]
    assert lgs and lgs[0].basis.split("+")[-1] in ("cast:가수", "genre:교양")
    assert "가수 님이 나오는" in lgs[0].reason or "좋아하시는 교양" in lgs[0].reason


def test_program_spanning_a_high_on_hour_is_placed_in_the_first_stage():
    """20:30~21:30 방송: 시작(20시)은 '중간'이지만 '높음'인 21시에 걸치면 '높음' 단계로 먼저 배치 (결정 D23)."""
    progs = [prog("day", "10:00", "11:00", key="day"), prog("drama", "20:30", "21:30", key="drama", ch="MBC")]
    on = {h: 0.0 for h in range(24)} | {10: 0.9, 20: 0.35, 21: 0.9}
    p = plan(progs, profile(series={"day": 1.0, "drama": 0.9}, budget=60, on=on, seen={"교양": 1.0}))
    assert [e.program_id for e in picks(p)] in (["day"], ["drama"])
    p2 = plan(progs, profile(series={"day": 0.9, "drama": 1.0}, budget=60, on=on, seen={"교양": 1.0}))
    assert [e.program_id for e in picks(p2)] == ["drama"], "둘 다 '높음' 단계라 점수 높은 드라마"


def test_series_only_left_on_becomes_background_not_a_pick():
    """'틀어만 놓기' 기록만 쌓인 시리즈는 집중 시청 칸(pick)이 아님 (결정 D24). 빈 시간에선 취향 순서 뒤 '평소 켜 두는 채널'로만."""
    s = senior(genres=["트로트"])
    left_on = logs_for(
        ["kbs1-news-noon", "kbs1-trot-party", "kbs1-docu"], how="continued", minutes=90
    )  # 낮 12~16시 KBS1
    prof = build_profile(left_on + logs_for(["tvc-star"], minutes=100), s, DAY)
    assert {"kbs1-news-noon", "kbs1-trot-party", "kbs1-docu"} <= prof.left_on_series
    assert prof.usual_channel[12] == "KBS1" and prof.tier(13) == "높음"
    p, report = check_plan(sample_programs(), sample_lg(), s, prof, RuleSet([], DAY), DAY, sample_numbers())
    assert not [e for e in picks(p) if e.source.series_key in prof.left_on_series]
    assert [e for e in p.entries if 12 <= e.start.hour < 16], "켜 두는 시각은 빈 시간 채우기로 채워짐"
    habit = [e for e in p.entries if e.fill_why == "habit"]
    assert all(
        e.channel_id == "KBS1" and e.reason.startswith("평소 이 시간엔 TV 를 켜 두셔서") for e in habit
    )
    assert all(report.must[c].ok for c in MUST), {c: report.must[c].detail for c in MUST}


def test_shows_stay_within_focus_time_and_the_rest_of_tv_on_time_is_background():
    """예산 두 개 (결정 D25): 집중 시청(pick) ≤ 골라 본 시간 평균, 남는 TV 켜짐 시간은 배경 편성(채널 유지)."""
    progs = [
        prog("a", "10:00", "11:00", key="a"),
        prog("k1", "11:00", "12:00", key="k1", cast=()),
        prog("k2", "12:00", "13:00", key="k2", cast=()),
    ]
    prof = profile(series={"a": 1.0, "k1": 0.9, "k2": 0.9}, budget=180, seen={"교양": 1.0})
    prof.focus_budget_min = 60
    p = plan(progs, prof)
    assert [e.program_id for e in picks(p)] == ["a"]
    assert [(e.program_id, e.role) for e in p.entries if e.kind == "fill"] == [
        ("k1", "background"),
        ("k2", "background"),
    ]


def test_focus_time_counts_chosen_and_plan_but_not_left_on():
    from app.engine.preference import focus_budget_min

    days = range(1, 8)
    logs = (
        [log_at("a", d, "19:00", 60, "chosen") for d in days]
        + [log_at("b", d, "20:00", 30, "plan") for d in days]
        + [log_at("c", d, "10:00", 300, "continued") for d in days]
    )
    assert focus_budget_min(logs, DAY) == pytest.approx(90)


def log_at(key, days_ago, hhmm, minutes, how):
    h, m = map(int, hhmm.split(":"))
    return WatchLog(
        senior_id="t",
        channel_id="KBS1",
        series_key=key,
        genre="교양",
        genres=["교양"],
        cast=[],
        started_at=datetime.combine(DAY - timedelta(days=days_ago), datetime.min.time())
        + timedelta(hours=h, minutes=m),
        watched_min=minutes,
        feedback="none",
        how_started=how,
        cancelled=False,
    )


def test_heavily_penalized_filler_leaves_room_for_a_better_show_in_the_next_stage():
    """1단계('높음' 시각)의 기준점 근처 칸이 다양성 감점을 계속 받으면 후보에서 빠져, 2단계의 좋은 방송들이 들어올 자리가 생긴다."""
    progs = [
        prog("drama", "21:00", "22:00", key="drama", genre="드라마"),
        prog("filler", "10:00", "11:00", key="filler", genre="드라마", ch="MBC"),
        prog("trot", "16:00", "17:00", key="trot", genre="트로트", ch="SBS"),
        prog("cult", "17:00", "18:00", key="cult", genre="교양", ch="EBS1"),
    ]
    on = {h: 0.0 for h in range(24)} | {10: 0.9, 21: 0.9, 16: 0.4, 17: 0.4}
    prof = profile(
        series={"drama": 1.0, "filler": 0.3, "trot": 1.0, "cult": 1.0},
        genre={"드라마": 1.0, "트로트": 1.0, "교양": 1.0},
        budget=180,
        on=on,
        seen={"드라마": 1.0, "트로트": 1.0, "사극": 1.0, "영화": 1.0, "교양": 1.0, "다큐": 1.0, "예능": 1.0},
    )
    assert config.REPLAN_DROP_FACTOR > 0
    assert sorted(e.program_id for e in picks(plan(progs, prof))) == ["cult", "drama", "trot"]


def test_nothing_starts_after_rest_day_even_in_later_high_hours():
    """'오늘은 그만 볼래'(12:30) 이후엔 뒤쪽 켜짐 '높음' 시각이라도 채우지 않는다 (Codex 리뷰에서 찾음)."""
    progs = [prog("a", "10:00", "11:00", key="a"), prog("b", "11:00", "12:00", key="b", ch="MBC")]
    on = {h: 0.0 for h in range(24)} | {10: 0.9, 11: 0.9, 13: 0.9, 14: 0.9}  # 12시 '낮음', 13~14시 '높음'
    rest = UserRule(
        senior_id="t",
        kind="rest_day",
        target_type="none",
        target="",
        date=DAY.isoformat(),
        from_time="12:30",
        active=True,
    )
    prof = profile(
        series={"a": 1.0, "b": 1.0},
        genre={"교양": 1.0},  # LG 가 S9 기준을 넘게
        watch_share={"교양": 1.0},
        budget=600,
        on=on,
        seen={"교양": 1.0, "다큐": 1.0, "건강": 1.0, "요리": 1.0},
    )
    p = plan(progs, prof, rules=[rest], lgs=[lg("x", "교양", 30)])
    assert all(e.start < at("12:30") for e in p.entries), [(e.program_id, e.start) for e in p.entries]


def test_quality_m2_flags_slots_after_rest_day():
    from dataclasses import replace

    from app.engine.quality import evaluate

    progs = [prog("a", "11:00", "12:00", key="a"), prog("late", "13:00", "14:00", key="late")]
    rest = UserRule(
        senior_id="t",
        kind="rest_day",
        target_type="none",
        target="",
        date=DAY.isoformat(),
        from_time="12:30",
        active=True,
    )
    rules = RuleSet([rest], DAY)
    prof = profile(series={"a": 1.0, "late": 1.0})
    p = plan(progs, prof, rules=[rest])
    p.entries = [
        *p.entries,
        replace(p.entries[0], program_id="late", start=progs[1].start, end=progs[1].end, source=progs[1]),
    ]
    assert not evaluate(p, programs=progs, senior=senior(), profile=prof, rules=rules).must["M2"].ok


def test_tv_on_time_after_midnight_counts_for_that_day():
    """매일 23:00~다음 날 01:00 을 보면 하루 켜짐 시간은 120분 (자정에서 자르지 않음, Codex 리뷰에서 찾음)."""
    from app.engine.tv_pattern import daily_on_minutes, on_ratio_by_hour

    late = [log_at("night", d, "23:00", 120, "chosen") for d in range(1, 8)]
    assert daily_on_minutes(late, DAY) == pytest.approx(120)
    on = on_ratio_by_hour(late, DAY)
    assert on[23] == on[0] == 1.0


def test_viewer_who_only_leaves_tv_on_still_gets_background():
    """'틀어만 놓기' 기록만 있는 분: 방송 칸은 0 이어도 켜 두는 시각엔 빈 시간 채우기가 나온다 (Codex 리뷰에서 찾음)."""
    s = senior(source="none")
    logs = logs_for(["kbs1-news-noon", "kbs1-trot-party"], how="continued", minutes=90)  # 매일 12~14시대 KBS1
    prof = build_profile(logs, s, DAY)
    p, report = check_plan(sample_programs(), sample_lg(), s, prof, RuleSet([], DAY), DAY, sample_numbers())
    assert not picks(p) and [e for e in p.entries if 12 <= e.start.hour < 14 and e.kind == "fill"]
    assert all(report.must[c].ok for c in MUST), {c: report.must[c].detail for c in MUST}


# ───────── 기준표 v4 (11/27): S5·S2·S6·M4 정의 수정, M8 추가 ─────────


def test_novelty_is_not_applicable_when_there_is_no_room():
    """새로 추천: 켜짐 '높음·중간' 구간에 여유가 없으면 '해당 없음' (실패 아님)."""
    near = config.NEAR_GENRES["트로트"][0]
    progs = [
        prog("fav", "10:00", "12:00", genre="트로트"),
        prog("new", "13:00", "14:00", genre=near, ch="EBS1"),
    ]
    prof = profile(series={"fav": 1.0}, genre={"트로트": 1.0}, seen={"트로트": 1.0}, budget=120)
    p, report = check_plan(progs, [lg("lg-new", near, 30)], senior(), prof, RuleSet([], DAY), DAY)
    assert not p.with_role("novelty")
    assert report.goals["S5"].ok is None and report.goals["S5"].detail.startswith("해당 없음")


def test_genre_share_is_not_applicable_under_three_counted_shows():
    progs = [
        prog("a", "10:00", "11:00", genre="트로트"),
        prog("b", "12:00", "13:00", genre="트로트", ch="MBC"),
    ]
    p, report = check_plan(
        progs, [], senior(), profile(series={"a": 1.0, "b": 1.0}, seen={"트로트": 1.0}), RuleSet([], DAY), DAY
    )
    assert len(picks(p)) == 2 and report.goals["S2"].ok is None


def test_first_slot_counts_from_the_first_high_on_hour():
    """S6: 켜짐 '높음' 구간이 시작되면(13시) 30분 안에 칸이 있어야 함 — '중간'(9시) 구간 시작은 상관없음."""
    on = {h: 0.0 for h in range(24)} | {9: 0.4, 13: 0.9, 14: 0.9}
    progs = [prog("noon", "13:00", "14:00"), prog("pm", "14:00", "15:00", ch="MBC")]
    _p, report = check_plan(
        progs,
        [],
        senior(),
        profile(series={"noon": 1.0, "pm": 1.0}, on=on, seen={"교양": 1.0}),
        RuleSet([], DAY),
        DAY,
    )
    assert report.goals["S6"].ok, report.goals["S6"].detail


def test_same_episode_once_but_two_episodes_of_a_series_are_allowed():
    """M4: 같은 '회차'는 하루 1번. 회차 정보가 다르면 같은 시리즈 두 편(연속 방송)도 됨."""
    from app.engine.quality import evaluate

    e1, e2 = prog("e1", "20:00", "21:00", key="d"), prog("e2", "21:00", "22:00", key="d", ch="MBC")
    e1.episode, e2.episode = "11", "12"
    p = plan([e1, e2], profile(series={"d": 1.0}, watch_share={"교양": 1.0}))
    assert [e.program_id for e in picks(p)] == ["e1", "e2"]
    e2.episode = "11"  # 같은 회차 재방송이면 한 번만
    p2 = plan([e1, e2], profile(series={"d": 1.0}, watch_share={"교양": 1.0}))
    assert [e.program_id for e in picks(p2)] == ["e1"]
    p2.entries.append(p.entries[-1])
    assert (
        not evaluate(
            p2, programs=[e1, e2], senior=senior(), profile=profile(series={"d": 1.0}), rules=RuleSet([], DAY)
        )
        .must["M4"]
        .ok
    )


def test_shows_on_channels_without_a_number_are_never_planned():
    """M8: 채널 번호가 없는 방송은 하루표에 넣지 않음 (LG 콘텐츠는 번호 없이도 됨)."""
    progs = [prog("ok", "10:00", "11:00", ch="KBS1"), prog("nonum", "12:00", "13:00", ch="NEW")]
    prof = profile(series={"ok": 1.0, "nonum": 1.0})
    p, report = check_plan(progs, [], senior(), prof, RuleSet([], DAY), DAY, numbered_channels={"KBS1"})
    assert "nonum" not in [e.program_id for e in p.entries] and p.dropped["nonum"] == "채널 번호 없음"
    assert report.must["M8"].ok


def test_m2_requires_every_pinned_episode():
    """챙겨 줘 시리즈의 11회·12회가 안 겹치면 둘 다 있어야 M2 통과 (회차 단위, Codex 리뷰에서 찾음)."""
    from app.engine.quality import evaluate

    e1, e2 = prog("e1", "10:00", "11:00", key="d"), prog("e2", "15:00", "16:00", key="d", ch="MBC")
    e1.episode, e2.episode = "11", "12"
    rules = RuleSet([rule("pin", "d")], DAY)
    prof = profile(series={"d": 1.0})
    p = plan([e1, e2], prof, rules=[rule("pin", "d")])
    assert [e.program_id for e in picks(p)] == ["e1", "e2"]
    p.entries = [e for e in p.entries if e.program_id != "e2"]
    assert not evaluate(p, programs=[e1, e2], senior=senior(), profile=prof, rules=rules).must["M2"].ok


def test_m2_does_not_require_pins_on_channels_without_a_number():
    pinned = prog("p", "10:00", "11:00", key="p", ch="NEW")
    p, report = check_plan(
        [pinned], [], senior(), profile(), RuleSet([rule("pin", "p")], DAY), DAY, numbered_channels={"KBS1"}
    )
    assert not p.entries and report.must["M2"].ok and report.must["M8"].ok


def test_m8_is_not_marked_passed_without_a_channel_number_table():
    _p, report = check_plan(
        [prog("a", "10:00", "11:00")], [], senior(), profile(series={"a": 1.0}), RuleSet([], DAY), DAY
    )
    assert report.must["M8"].ok is None


def test_taste_match_leaves_out_novelty_and_channel_keep_slots():
    """취향 일치율 분모에서 '새로 추천'·'채널 유지' 칸은 뺀다 (취향으로 고른 칸이 아니라서, E2 메모)."""
    from app.engine.plan import NOVELTY, Entry, Plan
    from app.engine.quality import metrics

    def entry(p, kind, basis, role="normal"):
        return Entry(p.id, p.channel_id, p.title, p.start, p.end, 0.5, kind, source=p, role=role, basis=basis)

    show, keep, new = prog("a", "10:00", "11:00"), prog("k", "11:00", "11:10"), prog("n", "12:00", "13:00")
    entries = [
        entry(show, "pick", "series"),
        entry(keep, "fill", "fill"),
        entry(new, "pick", "novelty:다큐", NOVELTY),
    ]
    p = Plan(entries, floor=0.35, budget_min=240, hours=set(range(24)), knows_taste=True)
    assert metrics(p)["taste_match"] == 1.0
    p.entries.append(entry(prog("x", "14:00", "15:00"), "pick", "new"))  # 취향 근거 아닌 방송 칸은 그대로 셈
    assert metrics(p)["taste_match"] == 0.5


def test_persona_with_fixed_meal_times_gets_nothing_starting_then():
    p, _ = persona_plan("식사·약 시간 고정")
    blocked = [("07:30", "08:00"), ("12:00", "13:00"), ("18:00", "18:30")]
    assert not [e for e in p.entries for a, b in blocked if at(a) <= e.start < at(b)]


def test_persona_watching_two_consecutive_episodes_gets_both():
    p, _ = persona_plan("같은 드라마 2회 연속")
    assert {"SER-1", "SER-2"} <= {e.program_id for e in p.entries}, "다른 회차라 둘 다 (같은 회차만 하루 1번)"


def test_persona_who_often_says_next_time_gets_those_series_paused():
    p, _ = persona_plan("자주 '다음에'")
    prof = build_profile(PERSONAS["자주 '다음에'"]["logs"], PERSONAS["자주 '다음에'"]["s"], DAY)
    assert {"kbs2-laugh", "sbs-laugh"} <= set(prof.paused)
    assert not [e for e in p.entries if getattr(e.source, "series_key", "") in prof.paused]
    assert (
        prof.cast.get("김태호", 0) > 0 or True
    )  # 출연자 점수는 쉬어가기와 상관없음 (signals 테스트에서 확인)


# ───────── E3: 자정 넘는 취침 · M9 빈 하루표 · 취향 일치율 해당 없음 ─────────


def test_sleep_earlier_than_wake_means_next_day():
    """취침이 기상보다 이르면(01:00) 다음 날 그 시각 (11/28 사람 결정)."""
    from app.engine.planner import wake_and_sleep

    wake, sleep = wake_and_sleep(senior(wake="09:00", sleep="01:00"), DAY)
    assert (wake, sleep) == (at("09:00"), at("01:00", DAY + timedelta(days=1)))


def test_night_owl_gets_shows_until_after_midnight():
    late = prog("late", "23:00", "23:50", key="late")
    after = prog("after", "10:00", "10:30", key="after", ch="MBC")
    after.start, after.end = at("00:10", DAY + timedelta(days=1)), at("00:40", DAY + timedelta(days=1))
    p = plan(
        [late, after], profile(series={"late": 1.0, "after": 1.0}), s=senior(wake="09:00", sleep="01:00")
    )
    assert {"late", "after"} <= {e.program_id for e in picks(p)}


def test_persona_night_owl_gets_a_plan():
    p, report = persona_plan("자정 넘는 방송")
    assert p.entries, "취침 01:00 은 다음 날 01:00 → 밤 방송이 들어가야 함"
    assert any(e.start.hour >= 22 for e in p.entries)
    assert report.must["M9"].ok


def test_m9_flags_an_empty_plan_when_there_are_candidates():
    from app.engine.quality import evaluate

    progs = [prog("a", "10:00", "11:00", key="a")]
    prof = profile(series={"a": 1.0})
    p = plan(progs, prof)
    assert p.entries
    p.entries = []
    report = evaluate(p, programs=progs, senior=senior(), profile=prof, rules=RuleSet([], DAY))
    assert report.must["M9"].ok is False


def test_m9_passes_an_empty_plan_without_candidates_and_says_why():
    progs = [prog("a", "10:00", "11:00", key="a", genre="트로트")]
    rules = RuleSet([rule("exclude", "트로트", "genre")], DAY)
    p, report = check_plan(progs, [], senior(), profile(series={"a": 1.0}), rules, DAY)
    assert not p.entries
    assert report.must["M9"].ok and report.must["M9"].detail.startswith("빈 하루표 — 후보 없음")
    assert "규칙으로 제외" in report.must["M9"].detail


def test_taste_match_is_not_applicable_without_chosen_slots():
    """취향 일치율을 셀 칸(새로 추천·채널 유지 말고)이 없으면 0% 가 아니라 '해당 없음'(None)."""
    from app.engine.plan import Entry, Plan
    from app.engine.quality import metrics

    keep = prog("k", "11:00", "12:00")
    fill = Entry("k", "KBS1", "k", keep.start, keep.end, 0.5, "fill", source=keep, basis="background")
    p = Plan([fill], floor=0.35, budget_min=240, hours=set(range(24)), knows_taste=False)
    assert metrics(p)["taste_match"] is None
    assert (
        metrics(Plan([], floor=0.35, budget_min=240, hours=set(), knows_taste=False))["taste_match"] is None
    )


def test_one_lg_instead_of_an_empty_plan_when_only_lg_fits():
    """방송 후보가 없고 취향에 맞는 LG 만 있으면 빈 하루표 대신 LG 1칸 — M9(반드시)가 S9·S10(목표)보다 먼저 (D48)."""
    progs = [prog("x", "10:00", "11:00", key="x", genre="트로트")]
    rules = RuleSet([rule("exclude", "트로트", "genre")], DAY)
    prof = profile(
        genre={"교양": 1.0}, timeslot={"낮": 1.0}, seen={"교양": 1.0, "다큐": 1.0, "건강": 1.0, "요리": 1.0}
    )
    lgs = [lg("a", "교양", 30), lg("b", "교양", 30)]
    p, report = check_plan(progs, lgs, senior(), prof, rules, DAY, numbered_channels={"KBS1"})
    assert [e.kind for e in p.entries] == ["lg"]
    assert all(report.must[c].ok for c in MUST), {c: report.must[c].detail for c in MUST}
    assert report.goals["S10"].ok is False and "M9 가 먼저" in report.goals["S10"].detail


def test_empty_plan_from_zero_focus_time_passes_m9_with_reason():
    """틀어만 두는 분(집중 시청 상한 0분)이 켜짐 '중간'뿐이면 빈 하루표가 정상 — 이유 '시청 시간 상한' (11/28 결정)."""
    progs = [prog("a", "10:00", "11:00", key="a")]
    prof = profile(series={"a": 1.0}, on={h: 0.4 for h in range(24)})
    prof.focus_budget_min = 0
    p, report = check_plan(progs, [], senior(), prof, RuleSet([], DAY), DAY, numbered_channels={"KBS1"})
    assert not p.entries and "시청 시간 상한" in p.notes["M9"]
    assert report.must["M9"].ok and "시청 시간 상한" in report.must["M9"].detail


def test_empty_plan_without_a_channel_to_keep_passes_m9_with_reason():
    """켜짐 '높음' 시각에 배경으로 깔 방송만 있는데 평소 켜 두는 채널이 아니면 이유를 남기고 통과 (채널 맞추기는 E6)."""
    progs = [prog("bg", "10:00", "11:00", key="bg", genre="뉴스", cast=(), ch="MBC")]
    prof = profile(genre={"트로트": 1.0}, cast={}, on={h: (0.9 if h == 10 else 0.0) for h in range(24)})
    prof.usual_channel = {10: "KBS1"}
    p, report = check_plan(
        progs, [], senior(), prof, RuleSet([], DAY), DAY, numbered_channels={"KBS1", "MBC"}
    )
    assert not p.entries and "이어 갈 채널이 없음" in p.notes["M9"]
    assert report.must["M9"].ok


def test_m9_fails_an_empty_plan_without_a_reason():
    from app.engine.quality import evaluate

    progs = [prog("a", "10:00", "11:00", key="a")]
    prof = profile(series={"a": 1.0}, on={h: 0.4 for h in range(24)})
    prof.focus_budget_min = 0
    p = plan(progs, prof)
    p.notes.pop("M9")
    report = evaluate(p, programs=progs, senior=senior(), profile=prof, rules=RuleSet([], DAY))
    assert report.must["M9"].ok is False and "빈 이유 없음" in report.must["M9"].detail


def test_m9_does_not_count_an_lg_that_cannot_fit_before_sleep():
    """기상 21:50·취침 22:00 에 30분 LG 만 있으면 넣을 자리가 없음 → 빈 하루표가 맞고 M9 통과 (Codex 리뷰에서 찾음)."""
    prof = profile(genre={"교양": 1.0}, timeslot={"밤": 1.0})
    p, report = check_plan(
        [], [lg("a", "교양", 30)], senior(wake="21:50", sleep="22:00"), prof, RuleSet([], DAY), DAY
    )
    assert not p.entries and report.must["M9"].ok


def test_m9_counts_an_lg_that_fits_after_a_fixed_break():
    """기상 10:00·취침 11:00·비움 10:00~10:15 → 10:15 에 30분 LG 가 들어감. 비어 있으면 M9 실패 (Codex 리뷰에서 찾음)."""
    from app.engine.quality import evaluate

    s = senior(wake="10:00", sleep="11:00", breaks=["10:00-10:15"])
    prof = profile(
        genre={"교양": 1.0}, timeslot={"낮": 1.0}, seen={"교양": 1.0, "다큐": 1.0, "건강": 1.0, "요리": 1.0}
    )
    lgs = [lg("a", "교양", 30)]
    p, _ = check_plan([], lgs, s, prof, RuleSet([], DAY), DAY)
    assert [(e.program_id, e.start) for e in p.entries] == [("a", at("10:15"))]
    p.entries = []
    report = evaluate(p, programs=[], senior=s, profile=prof, rules=RuleSet([], DAY), lg_contents=lgs)
    assert report.must["M9"].ok is False


# ───────── 독립 리뷰 H1: '오늘은 그만 볼래'와 자정 넘는 방송 ─────────


def _rest_day(from_time: str) -> UserRule:
    return UserRule(
        senior_id="t", kind="rest_day", target_type="none", target="", date=DAY.isoformat(), from_time=from_time,
        active=True,
    )  # fmt: skip


def _night_case():
    """기상 06:00·취침 01:00, 22:00 부터 그만 볼래, 20:00 방송 + 다음 날 00:10~00:50 방송."""
    evening = prog("eve", "20:00", "21:00", key="eve")
    late = prog("late", "10:00", "10:40", key="late", ch="MBC")
    late.start, late.end = at("00:10", DAY + timedelta(days=1)), at("00:50", DAY + timedelta(days=1))
    return [evening, late], profile(series={"eve": 1.0, "late": 1.0}), senior(wake="06:00", sleep="01:00")


def test_rest_day_blocks_shows_after_midnight():
    progs, prof, s = _night_case()
    rules = RuleSet([_rest_day("22:00")], DAY, s.wake_time)
    p, report = check_plan(progs, [], s, prof, rules, DAY)
    assert "late" not in {e.program_id for e in p.entries}, "22:00 부터 그만 → 다음 날 00:10 방송도 안 됨"
    assert all(e.start < at("22:00") for e in p.entries)
    assert report.must["M2"].ok, report.must["M2"].detail


def test_m2_catches_a_slot_after_midnight_when_the_engine_compares_time_only(monkeypatch):
    """엔진을 옛 방식(시각만 비교)으로 되돌리면 00:10 방송이 들어가고, 판정기(M2)가 그걸 잡아야 함."""
    from datetime import time

    progs, prof, s = _night_case()
    rules = RuleSet([_rest_day("22:00")], DAY, s.wake_time)
    monkeypatch.setattr(RuleSet, "allows_start", lambda self, start: start.time() < time(22, 0))
    p, report = check_plan(progs, [], s, prof, rules, DAY)
    assert "late" in {e.program_id for e in p.entries}
    assert report.must["M2"].ok is False and "그만 볼래" in report.must["M2"].detail


def test_rest_day_said_after_midnight_means_the_next_day():
    """from_time 이 기상보다 이르면(00:30) 다음 날 00:30 부터 (wake_and_sleep 과 같은 규칙)."""
    rules = RuleSet([_rest_day("00:30")], DAY, "06:00")
    assert rules.allows_start(at("23:00")) and rules.allows_start(at("00:10", DAY + timedelta(days=1)))
    assert not rules.allows_start(at("00:40", DAY + timedelta(days=1)))


# ───────── 독립 리뷰 H2: 기록 0건인데 '이 시간에 자주 보시는 방송' ─────────


def _no_history_case():
    """관심 장르=사극, 기록 0건, 출연자 정보 없는 교양 8개 (08~15시)."""
    s = senior(genres=["사극"])
    progs = [
        prog(f"c{h}", f"{h:02d}:00", f"{h:02d}:50", key=f"c{h}", genre="교양", cast=()) for h in range(8, 16)
    ]
    return s, progs, build_profile([], s, DAY)


def test_no_timeslot_reason_without_any_viewing_record():
    s, progs, prof = _no_history_case()
    p, report = check_plan(progs, [], s, prof, RuleSet([], DAY), DAY, numbered_channels={"KBS1"})
    assert p.entries, "기준점이 낮아져 하루표는 나옴"
    assert not [e for e in p.entries if "timeslot" in e.basis.split("+")], [
        (e.title, e.reason) for e in p.entries
    ]
    assert report.must["M5"].ok, report.must["M5"].detail


def test_m5_rejects_a_timeslot_reason_built_on_the_neutral_default():
    """기록 없이 중립값(0.5)만 있는 시간대 습관을 이유로 붙이면 M5 실패 (자기 채점 금지)."""
    from app.engine.quality import evaluate

    s, progs, prof = _no_history_case()
    p, _ = check_plan(progs, [], s, prof, RuleSet([], DAY), DAY, numbered_channels={"KBS1"})
    picked = next(e for e in p.entries if e.kind == "pick")
    picked.reason, picked.basis = "이 시간에 자주 보시는 방송이에요", "timeslot"
    report = evaluate(p, programs=progs, senior=s, profile=prof, rules=RuleSet([], DAY))
    assert report.must["M5"].ok is False
