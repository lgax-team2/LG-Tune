"""좋은 하루표 기준표 v3 (backend/app/engine/QUALITY.md) 테스트.

- 반드시(M1~M7): 샘플 3명 + 테스트 페르소나 6명 모두 통과해야 함
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
MUST = ["M1", "M2", "M3", "M4", "M5", "M6", "M7"]


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


def senior(wake="06:00", sleep="22:00", series=(), cast=(), genres=(), family=(), source="child"):
    return Senior(
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


def profile(series=None, cast=None, genre=None, timeslot=None, budget=240.0, watch_share=None, seen=None):
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
    series_keys: list[str], minutes: float = 60.0, days: int = 14, how: str = "chosen"
) -> list[WatchLog]:
    """오늘 편성표에서 그 시리즈가 하는 시각에, 지난 days 일 동안 매일 본 기록."""
    by_key = {}
    for p in sample_programs():
        by_key.setdefault(p.series_key, p)
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
}


def persona_plan(name):
    p = PERSONAS[name]
    prof = build_profile(p["logs"], p["s"], DAY)
    return check_plan(
        programs=sample_programs(),
        lg_contents=sample_lg(),
        senior=p["s"],
        profile=prof,
        rules=RuleSet(p["rules"], DAY),
        day=DAY,
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
    assert p.bands == {"저녁"}
    assert p.budget_min == pytest.approx(60)
    assert sum(e.minutes for e in picks(p)) <= 60


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
    """두 칸(10시·11시)에 트로트·다큐가 하나씩 겹쳐 있음: 보통은 반반, 트로트만 보는 분은 트로트 두 칸."""
    progs = [prog(f"t{h}", f"{h}:00", f"{h + 1}:00", genre="트로트") for h in (10, 11)]
    progs += [prog(f"d{h}", f"{h}:00", f"{h + 1}:00", genre="다큐", ch="EBS1") for h in (10, 11)]
    base = {"genre": {"트로트": 1.0, "다큐": 0.9}, "budget": 120, "seen": {"트로트": 1.0, "다큐": 1.0}}
    half = [e.source.genre for e in picks(plan(progs, profile(**base)))]
    assert sorted(half) == ["다큐", "트로트"]
    loves = [e.source.genre for e in picks(plan(progs, profile(**base, watch_share={"트로트": 1.0})))]
    assert loves == ["트로트", "트로트"], "실제로 트로트만 보는 분은 상한이 그 비율까지"


def test_no_three_same_genre_in_a_row():
    progs = [prog(f"t{i}", f"{10 + i}:00", f"{11 + i}:00", genre="트로트") for i in range(3)]
    progs += [prog("d", "11:00", "12:00", genre="다큐", ch="EBS1")]
    prof = profile(genre={"트로트": 1.0, "다큐": 0.7}, watch_share={"트로트": 1.0})
    genres = [e.source.genre for e in picks(plan(progs, prof))]
    assert all(not (a == b == c) for a, b, c in zip(genres, genres[1:], genres[2:])), genres


# ───────── S9 LG 콘텐츠 ─────────


def test_lg_content_needs_taste_score_near_floor():
    progs = [prog("a", "10:00", "12:00"), prog("b", "13:00", "15:00")]
    prof = profile(series={"a": 1.0, "b": 1.0}, genre={"트로트": 1.0}, cast={})
    liked = plan(progs, prof, lgs=[lg("liked", "트로트", 30, cast=())])  # 0.15 < 0.35×0.8
    assert not [e for e in liked.entries if e.kind == "lg"]
    prof2 = profile(series={"a": 1.0, "b": 1.0}, genre={"트로트": 1.0})
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
    """시청 시간대(낮 09:00~) 시작 30분 안에 첫 칸 (방송이 늦게 시작하면 LG 로)."""
    progs = [prog("late", "13:00", "15:00")]
    prof = profile(series={"late": 1.0}, genre={"교양": 1.0}, timeslot={"아침": 0.1, "낮": 0.9})
    p = plan(progs, prof, lgs=[lg("morning", "교양", 30)])
    assert p.entries[0].start <= at("09:30")


# ───────── S7 출연자 공정성 ─────────


def test_removing_cast_info_changes_score_by_at_most_002():
    """출연자 취향과 상관없는 방송에서 출연자 칸을 지워도 점수가 거의 같다."""
    prof = profile(series={"x": 0.8}, genre={"교양": 0.6}, cast={"좋아하는 가수": 1.0})
    with_cast = score_program(prog("x", "20:00", "21:00", cast=["모르는 배우"]), prof, []).score
    without = score_program(prog("x", "20:00", "21:00", cast=[]), prof, []).score
    assert abs(with_cast - without) <= 0.02


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
    assert p.dropped["B"] == "겹치는 챙겨 줘"


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
    assert "new" not in [e.program_id for e in p.entries]
