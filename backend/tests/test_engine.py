"""하루표 엔진 테스트 (docs/약속.md 6절 규칙 6개).

1 점수 공식 · 2 신호 세기 · 3 본 날 기준 반감기 + 콜드 스타트
4 음성 명령 규칙(빼기·챙기기·오늘만·쉬기) · 5 DP 배치 · 6 빈 시간(채널 유지 / LG)
"""

from datetime import date, datetime, timedelta
from itertools import pairwise

import pytest

from app.engine import config
from app.engine.planner import Candidate, build_plan, select_best
from app.engine.preference import Profile, build_profile, weigh_logs
from app.engine.rules import RuleSet
from app.engine.scoring import score_program
from app.models.db import LgContent, Program, Senior, UserRule, WatchLog

DAY = date(2026, 12, 1)


def at(hhmm: str, d: date = DAY) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m)


def prog(pid, start, end, key=None, genre="교양", cast=(), ch="KBS1", is_new=False, is_live=False):
    return Program(
        id=pid,
        channel_id=ch,
        title=pid,
        series_key=key or pid,
        genre=genre,
        start=at(start),
        end=at(end),
        cast=list(cast),
        is_new=is_new,
        is_live=is_live,
    )


def log(key, d, minutes=30.0, how="chosen", genre="교양", cast=(), hhmm="20:00", cancelled=False):
    return WatchLog(
        senior_id="s1",
        channel_id="KBS1",
        series_key=key,
        genre=genre,
        cast=list(cast),
        started_at=at(hhmm, d),
        watched_min=minutes,
        feedback="none",
        how_started=how,
        cancelled=cancelled,
    )


def senior(wake="06:00", sleep="22:00", series=(), cast=(), genres=(), family=()):
    return Senior(
        id="s1",
        name="테스트",
        age=75,
        wake_time=wake,
        sleep_time=sleep,
        pref_source="child",
        seed_prefs={"series": list(series), "cast": list(cast), "genres": list(genres)},
        family_picks=list(family),
    )


def rule(kind, target="", target_type="series", d=None, from_time=None, active=True):
    return UserRule(
        senior_id="s1",
        kind=kind,
        target_type=target_type,
        target=target,
        date=d,
        from_time=from_time,
        active=active,
    )


def lg(cid, genre, minutes, cast=()):
    return LgContent(id=cid, title=cid, genre=genre, cast=list(cast), duration_min=minutes, source="LG채널")


def flat_profile(series=None, cast=None, genre=None, timeslot=None):
    return Profile(
        series=series or {},
        cast=cast or {},
        genre=genre or {},
        timeslot=timeslot or {},
        history_share=0.0,
        n_logs=0,
    )


# ───────── 규칙 2·3: 취향 추정 ─────────


def test_short_and_cancelled_logs_are_ignored():
    d = DAY - timedelta(days=1)
    weights = weigh_logs([log("a", d, minutes=4.9), log("b", d, cancelled=True), log("c", d)], DAY)
    assert [w.log.series_key for w in weights] == ["c"]


def test_chosen_counts_more_than_continued_or_plan():
    d = DAY - timedelta(days=1)
    weights = {
        w.log.series_key: w.weight
        for w in weigh_logs([log("a", d), log("b", d, how="continued"), log("c", d, how="plan")], DAY)
    }
    assert weights["a"] == 1.0
    assert weights["b"] == weights["c"] == config.SIGNAL["continued"] == 0.3


def test_half_life_counts_viewing_days_not_calendar_days():
    """주말만 보는 분: 본 날 14일 전 기록은 달력으로 7주 전이어도 절반만큼 반영."""
    weekend_days = sorted(
        {DAY - timedelta(days=n) for n in range(1, 60) if (DAY - timedelta(days=n)).weekday() >= 5}
    )
    days = weekend_days[-15:]  # 최근 본 날 15일 (가장 오래된 날 = 본 날 기준 14일 전)
    logs = [log("old", days[0])] + [log("mid", d) for d in days[1:-1]] + [log("new", days[-1])]
    w = {x.log.series_key: x.weight for x in weigh_logs(logs, DAY) if x.log.series_key in ("old", "new")}
    assert (DAY - days[0]).days > 40, "달력으로는 6주 넘게 전"
    assert w["old"] == pytest.approx(w["new"] * 0.5)


def test_logs_older_than_60_days_are_dropped():
    assert weigh_logs([log("a", DAY - timedelta(days=config.MAX_AGE_DAYS + 1))], DAY) == []


def test_cold_start_uses_first_day_info():
    p = build_profile([], senior(series=["k"], cast=["송미란"], genres=["트로트"]), DAY)
    assert p.history_share == 0
    assert p.series["k"] == 1.0 and p.cast["송미란"] == 1.0 and p.genre["트로트"] == 1.0
    assert p.timeslot_score(at("20:00")) == config.NEUTRAL_TIMESLOT


def test_history_share_grows_with_number_of_logs():
    logs = [log("a", DAY - timedelta(days=i + 1)) for i in range(10)]
    p = build_profile(logs, senior(), DAY)
    assert p.history_share == pytest.approx(10 / (10 + config.COLD_START_K))


def test_left_on_tv_counts_less_than_chosen_show():
    """틀어만 놓고 오래 둔 방송(이어짐)보다 짧게라도 직접 고른 방송이 취향에 더 크게 남는다."""
    d = DAY - timedelta(days=1)
    p = build_profile(
        [log("left-on", d, minutes=120, how="continued"), log("picked", d, minutes=20)], senior(), DAY
    )
    assert p.series["picked"] > p.series["left-on"]


# ───────── 규칙 1: 점수 ─────────


def test_score_formula_weights():
    p = flat_profile(series={"k": 1.0})
    s = score_program(prog("x", "10:00", "11:00", key="k"), p, family_picks=[])
    assert s.score == pytest.approx(0.30)
    s2 = score_program(prog("x", "10:00", "11:00", key="k", is_new=True), p, family_picks=["k"])
    assert s2.score == pytest.approx(0.30 + 0.10 + 0.05)
    assert sum(config.WEIGHTS.values()) == pytest.approx(1.0)


def test_cast_uses_best_liked_person():
    p = flat_profile(cast={"송미란": 1.0, "김태호": 0.2})
    s = score_program(prog("x", "10:00", "11:00", cast=["김태호", "송미란"]), p, family_picks=[])
    assert s.parts["cast"] == pytest.approx(0.25)
    assert s.top_cast == "송미란"


# ───────── 규칙 5: DP 배치 ─────────


def test_dp_beats_greedy():
    """점수 1등(A)만 욕심내면 B+C 를 놓친다. DP 는 점수×길이 합이 큰 B+C 를 고른다."""
    a = Candidate(key="A", start=at("10:00"), end=at("11:30"), score=0.95)
    b = Candidate(key="B", start=at("10:00"), end=at("11:00"), score=0.80)
    c = Candidate(key="C", start=at("11:00"), end=at("12:00"), score=0.80)
    assert [x.key for x in select_best([a, b, c])] == ["B", "C"]


def plan(programs, profile=None, s=None, rules=(), lgs=()):
    return build_plan(
        programs=programs,
        lg_contents=list(lgs),
        senior=s or senior(),
        profile=profile or flat_profile(series={p.series_key: 1.0 for p in programs}, genre={"교양": 1.0}),
        rules=RuleSet(list(rules), DAY),
        day=DAY,
    )


def test_plan_skips_shows_before_wake_and_below_threshold():
    progs = [
        prog("early", "05:00", "05:50"),
        prog("ok", "10:00", "11:00"),
        prog("weak", "12:00", "13:00"),
    ]
    p = flat_profile(series={"early": 1, "ok": 1}, genre={"교양": 1})  # weak = 장르만 0.15 < 0.35
    keys = [e.program_id for e in plan(progs, profile=p) if e.kind == "pick"]
    assert keys == ["ok"]


def test_show_starting_before_sleep_is_allowed_even_if_it_ends_after():
    """취침(22:00) 전에 '시작'하면 끝나는 시간과 상관없이 넣는다."""
    progs = [prog("late", "21:30", "22:30")]
    assert [e.program_id for e in plan(progs)] == ["late"]


def test_show_starting_at_or_after_sleep_is_not_allowed():
    progs = [prog("at-sleep", "22:00", "23:00"), prog("after", "22:30", "23:30")]
    assert plan(progs) == []


def test_morning_gap_of_20min_or_more_gets_lg_content_at_wake_time():
    """기상(06:00)~첫 방송(09:00) 사이도 빈 시간: 20분 이상이면 LG 콘텐츠를 기상 시각부터."""
    progs = [prog("first", "09:00", "10:00")]
    entries = plan(progs, lgs=[lg("morning", "교양", 30)])
    assert [(e.program_id, e.kind) for e in entries] == [("morning", "lg"), ("first", "pick")]
    assert entries[0].start == at("06:00") and entries[0].end == at("06:30")


def test_morning_gap_under_20min_stays_empty():
    """기상 직후 짧은 빈 시간은 앞 채널이 없으니 채우지 않고 비워 둔다."""
    progs = [prog("first", "06:15", "07:00")]
    entries = plan(progs, lgs=[lg("short", "교양", 20)])
    assert [(e.program_id, e.kind) for e in entries] == [("first", "pick")]


# ───────── 규칙 4: 음성 명령 규칙 ─────────


def test_excluded_series_never_appears_anywhere():
    """'이거 이제 안 볼래' → 점수가 최고여도, 빈 시간 채우기로도 절대 안 나온다."""
    progs = [
        prog("fav", "10:00", "11:00", key="fav"),
        prog("hated", "11:00", "11:10", key="hated", ch="KBS1"),  # 짧은 빈 시간에 채널 유지로 들어갈 자리
        prog("next", "11:10", "12:00", key="next"),
    ]
    p = flat_profile(series={"fav": 1, "hated": 1, "next": 1}, genre={"교양": 1})
    assert "hated" in [e.program_id for e in plan(progs, profile=p)], "규칙이 없으면 들어가는 방송"
    entries = plan(progs, profile=p, rules=[rule("exclude", "hated")])
    assert "hated" not in [e.program_id for e in entries]
    assert [e.program_id for e in entries] == ["fav", "next"]


def test_excluded_genre_blocks_lg_contents_too():
    progs = [prog("a", "10:00", "11:00"), prog("b", "12:00", "13:00")]
    lgs = [lg("lg-trot", "트로트", 30)]
    assert "lg-trot" in [e.program_id for e in plan(progs, lgs=lgs)], "규칙이 없으면 들어감"
    entries = plan(progs, rules=[rule("exclude", "트로트", target_type="genre")], lgs=lgs)
    assert all(e.program_id != "lg-trot" for e in entries)


def test_pinned_series_is_included_even_with_low_score():
    progs = [prog("news", "19:00", "20:00", key="news"), prog("fav", "19:00", "20:00", key="fav", ch="MBC")]
    p = flat_profile(series={"news": 0.0, "fav": 1.0}, genre={"교양": 1})
    assert [e.program_id for e in plan(progs, profile=p)] == ["fav"], "규칙이 없으면 fav"
    keys = [e.program_id for e in plan(progs, profile=p, rules=[rule("pin", "news")])]
    assert "news" in keys and "fav" not in keys


def test_skip_today_only_affects_that_day():
    progs = [prog("a", "10:00", "11:00", key="a")]
    assert plan(progs, rules=[rule("skip_today", "a", d=DAY.isoformat())]) == []
    assert [e.program_id for e in plan(progs, rules=[rule("skip_today", "a", d="2026-11-30")])] == ["a"]


def test_rest_day_empties_rest_of_today():
    progs = [prog("a", "10:00", "11:00"), prog("b", "15:00", "16:00")]
    entries = plan(progs, rules=[rule("rest_day", target_type="none", d=DAY.isoformat(), from_time="12:00")])
    assert [e.program_id for e in entries] == ["a"]


def test_undone_rule_is_ignored():
    progs = [prog("a", "10:00", "11:00", key="a")]
    assert [e.program_id for e in plan(progs, rules=[rule("exclude", "a", active=False)])] == ["a"]


# ───────── 규칙 6: 빈 시간 ─────────


def test_short_gap_keeps_same_channel():
    progs = [
        prog("a", "10:00", "11:00", ch="KBS1"),
        prog("filler", "11:00", "11:15", ch="KBS1", key="filler"),
        prog("b", "11:15", "12:00", ch="KBS1"),
    ]
    p = flat_profile(series={"a": 1, "b": 1}, genre={"교양": 1})  # filler 는 장르만 0.15 → pick 은 아님
    entries = plan(progs, profile=p)
    assert [(e.program_id, e.kind) for e in entries] == [("a", "pick"), ("filler", "fill"), ("b", "pick")]


def test_long_gap_gets_best_fitting_lg_content():
    progs = [prog("a", "10:00", "11:00"), prog("b", "12:00", "13:00")]
    p = flat_profile(series={"a": 1, "b": 1}, genre={"교양": 1, "트로트": 1.0, "다큐": 0.2})
    lgs = [lg("too-long", "트로트", 90), lg("trot", "트로트", 30), lg("docu", "다큐", 45)]
    entries = plan(progs, profile=p, lgs=lgs, s=senior(wake="10:00"))  # 아침 빈 시간 없이 방송 사이만 봄
    middle = [e for e in entries if e.kind == "lg"]
    assert [e.program_id for e in middle] == ["trot"]
    assert middle[0].start == at("11:00") and middle[0].end == at("11:30")


def test_gap_too_long_for_fill_and_no_lg_fit_stays_empty():
    progs = [prog("a", "10:00", "11:00"), prog("b", "12:00", "13:00")]
    entries = plan(progs, lgs=[])
    assert [e.kind for e in entries] == ["pick", "pick"]


# ───────── 샘플 전체로 한 번에 ─────────


@pytest.fixture
def sample_session(tmp_path):
    from app.models.db import init_db, make_engine, make_session_factory
    from app.models.sample import load_sample

    engine = make_engine(tmp_path / "e.db")
    init_db(engine)
    with make_session_factory(engine)() as s:
        load_sample(s)
        yield s


@pytest.mark.parametrize("sid", ["s1", "s2", "s3"])
def test_sample_seniors_get_valid_plans(sample_session, sid):
    from app.engine.service import make_schedule

    res = make_schedule(sample_session, sid, DAY)
    items = res.items
    assert items, f"{sid} 하루표가 비었음 (콜드 스타트도 첫날부터 있어야 함)"
    s = sample_session.get(Senior, sid)
    for a, b in pairwise(items):
        assert a.end <= b.start, "겹침"
    assert items[0].start.strftime("%H:%M") >= s.wake_time
    assert items[-1].start.strftime("%H:%M") < s.sleep_time, "취침 전에 시작해야 함"
    assert all(i.reason for i in items)


def test_sample_voice_rules_are_respected(sample_session):
    from app.engine.service import make_schedule

    s1 = make_schedule(sample_session, "s1", DAY)
    assert all(not i.program_id.startswith("MBC-20261201-2030") for i in s1.items), "s1 이 뺀 '푸른 바다'"
    s2 = make_schedule(sample_session, "s2", DAY)
    assert any(i.program_id == "KBS1-20261201-1900" for i in s2.items), "s2 가 챙겨 달라고 한 저녁 뉴스"


# ───────── 샘플을 눈으로 보다 찾은 문제 ─────────


def test_long_show_does_not_push_out_favorite():
    """90분짜리(0.81)가 겹치는 60분짜리 최애 드라마(0.9)를 길이만으로 밀어내면 안 된다."""
    a = Candidate(key="long", start=at("20:00"), end=at("21:30"), score=0.81)
    b = Candidate(key="fav", start=at("20:30"), end=at("21:30"), score=0.90)
    assert [x.key for x in select_best([a, b])] == ["fav"]


def test_same_lg_content_is_used_once_a_day():
    progs = [prog("a", "10:00", "11:00"), prog("b", "12:00", "13:00"), prog("c", "14:00", "15:00")]
    lgs = [lg("best", "교양", 30), lg("second", "교양", 30, cast=())]
    entries = [e.program_id for e in plan(progs, lgs=lgs) if e.kind == "lg"]
    assert len(entries) == len(set(entries)) == 2


def test_reason_uses_correct_korean_ending():
    from app.engine.reason import ieyo

    assert ieyo("프로그램") == "프로그램이에요"
    assert ieyo("트로트") == "트로트예요"
    assert ieyo("방송") == "방송이에요"
    assert ieyo("드라마") == "드라마예요"
