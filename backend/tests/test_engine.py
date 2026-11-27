"""하루표 엔진 테스트 (docs/약속.md 6절 규칙 6개).

1 점수 공식 · 2 신호 세기 · 3 본 날 기준 반감기 + 콜드 스타트
4 음성 명령 규칙(빼기·챙기기·오늘만·쉬기) · 5 DP 배치 · 6 빈 시간(채널 유지 / LG)
"""

from datetime import date, datetime, timedelta
from itertools import pairwise

import pytest
from sqlalchemy import select

from app.engine import config
from app.engine.planner import build_plan
from app.engine.preference import Profile, build_profile, weigh_logs
from app.engine.rules import RuleSet
from app.engine.scoring import score_program
from app.engine.selection import Candidate, select_best
from app.models.db import LgContent, Program, Senior, UserRule, WatchLog

DAY = date(2026, 12, 1)


def at(hhmm: str, d: date = DAY) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m)


def prog(pid, start, end, key=None, genre="교양", cast=(), ch="KBS1", is_new=False, is_live=False, genres=()):
    return Program(
        id=pid,
        channel_id=ch,
        title=pid,
        series_key=key or pid,
        genre=genre,
        genres=list(genres),
        start=at(start),
        end=at(end) if end != "24:30" else at("00:30", DAY + timedelta(days=1)),
        cast=list(cast),
        is_new=is_new,
        is_live=is_live,
    )


def log(key, d, minutes=30.0, how="chosen", genre="교양", cast=(), hhmm="20:00", cancelled=False, genres=()):
    return WatchLog(
        senior_id="s1",
        channel_id="KBS1",
        series_key=key,
        genre=genre,
        genres=list(genres),
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


def lg(
    cid, genre, minutes, cast=("가수",)
):  # 기본 출연자 "가수" = 아래 plan() 기본 취향이 좋아하는 사람 (S9 점수 기준)
    return LgContent(id=cid, title=cid, genre=genre, cast=list(cast), duration_min=minutes, source="LG채널")


def flat_profile(series=None, cast=None, genre=None, timeslot=None, budget=None):
    return Profile(
        series=series or {},
        cast=cast or {},
        genre=genre or {},
        timeslot=timeslot or {},
        history_share=0.0,
        n_logs=0,
        daily_budget_min=budget or config.DEFAULT_BUDGET_MIN,
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
    known_cast = ["누군가"]  # 출연자 정보가 있어야 가중치가 그대로 (없으면 ÷0.75 — 아래 호환 테스트)
    s = score_program(prog("x", "10:00", "11:00", key="k", cast=known_cast), p, family_picks=[])
    assert s.score == pytest.approx(0.30)
    s2 = score_program(
        prog("x", "10:00", "11:00", key="k", is_new=True, cast=known_cast), p, family_picks=["k"]
    )
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
    """하루표 칸 목록 (Plan.entries)."""
    return build_plan(
        programs=programs,
        lg_contents=list(lgs),
        senior=s or senior(),
        profile=profile
        or flat_profile(
            series={p.series_key: 1.0 for p in programs}, genre={"교양": 1.0}, cast={"가수": 1.0}
        ),
        rules=RuleSet(list(rules), DAY),
        day=DAY,
    ).entries


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
    progs = [prog("first", "09:00", "11:00")]  # LG 비율 30% 안에 들게 방송을 2시간으로
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
    p = flat_profile(series={"a": 1, "b": 1}, genre={"교양": 1, "트로트": 1}, cast={"가수": 1})
    assert "lg-trot" in [e.program_id for e in plan(progs, profile=p, lgs=lgs)], "규칙이 없으면 들어감"
    entries = plan(progs, profile=p, rules=[rule("exclude", "트로트", target_type="genre")], lgs=lgs)
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
    p = flat_profile(
        series={"a": 1, "b": 1}, genre={"교양": 1, "트로트": 1.0, "다큐": 0.2}, cast={"가수": 1.0}
    )
    p.genre_seen_share = {"다큐": 1.0, "건강": 1.0, "요리": 1.0}  # 새로 추천(S5)할 안 본 장르가 없게
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
    lgs = [lg("best", "교양", 30), lg("second", "교양", 30)]
    entries = [e.program_id for e in plan(progs, lgs=lgs) if e.kind == "lg"]
    assert len(entries) == len(set(entries)) == 2


def test_reason_uses_correct_korean_ending():
    from app.engine.reason import ieyo

    assert ieyo("프로그램") == "프로그램이에요"
    assert ieyo("트로트") == "트로트예요"
    assert ieyo("방송") == "방송이에요"
    assert ieyo("드라마") == "드라마예요"


# ───────── 외부 편성표 호환: 장르 여러 개 · 빠진 정보 ─────────


def test_profile_counts_every_genre_of_a_log():
    """장르가 [트로트, 예능] 인 기록 한 건은 두 장르에 같은 무게로 더해진다."""
    p = build_profile(
        [log("star", DAY - timedelta(days=1), genre="트로트", genres=["트로트", "예능"])], senior(), DAY
    )
    assert p.genre["트로트"] == p.genre["예능"] > 0


def test_log_without_genres_list_uses_main_genre():
    p = build_profile([log("news", DAY - timedelta(days=1), genre="뉴스")], senior(), DAY)
    assert p.genre["뉴스"] > 0


def test_genre_score_uses_best_liked_of_many():
    show = prog("star", "20:00", "21:00", genre="예능", genres=["예능", "트로트"], cast=["가수"])
    s = score_program(show, flat_profile(genre={"예능": 0.2, "트로트": 1.0}), [])
    assert s.parts["genre"] == pytest.approx(config.WEIGHTS["genre"] * 1.0)
    assert s.top_genre == "트로트"


def test_unknown_genre_scores_zero_without_error():
    show = prog("odd", "20:00", "21:00", genre="처음 보는 장르", cast=["누군가"])
    s = score_program(show, flat_profile(genre={"트로트": 1.0}), [])
    assert s.parts["genre"] == 0.0


def test_missing_cast_counts_like_unknown_cast():
    """출연자 정보가 없으면 출연자 칸 = MISSING_CAST_SCORE(기본 0) — 모르는 출연자가 나오는 방송과 같은 점수 (기준표 S7)."""
    profile = flat_profile(series={"news": 1.0}, genre={"교양": 1.0})
    no_cast = score_program(prog("news", "20:00", "21:00"), profile, [])
    unknown = score_program(prog("news", "20:00", "21:00", cast=["모르는 사람"]), profile, [])
    assert config.MISSING_CAST_SCORE == 0.0
    assert no_cast.score == pytest.approx(unknown.score) == pytest.approx(0.30 + 0.15)
    assert sum(no_cast.parts.values()) == pytest.approx(no_cast.score)


def test_missing_is_new_is_live_defaults_to_false(tmp_path):
    """외부 편성표에 새 회차·생방송 칸이 없어도 DB 에 넣으면 false, 점수의 새 회차 항목은 0."""
    from app.models.db import init_db, make_engine, make_session_factory

    engine = make_engine(tmp_path / "m.db")
    init_db(engine)
    with make_session_factory(engine)() as session:
        session.add(
            Program(
                id="x",
                channel_id="KBS1",
                title="x",
                series_key="x",
                genre="뉴스",
                start=at("10:00"),
                end=at("11:00"),
            )
        )
        session.commit()
        p = session.get(Program, "x")
        assert p.is_new is False and p.is_live is False and p.genres == [] and p.cast == []
        assert score_program(p, flat_profile(), []).parts["fresh"] == 0.0
    engine.dispose()


def test_show_crossing_midnight_is_handled():
    """23:30~다음 날 00:30 방송: 취침(23:50) 전에 시작하니 들어간다."""
    entries = plan([prog("late", "23:30", "24:30")], s=senior(sleep="23:50"))
    assert [e.program_id for e in entries] == ["late"]
    assert entries[0].end == at("00:30", DAY + timedelta(days=1))


def test_series_key_equal_to_title_works():
    """외부 편성표에 회차 묶음 키가 없어 제목을 그대로 쓴 경우에도 시청 기록과 이어진다."""
    title = "노래 교실 (재)"
    profile = build_profile([log(title, DAY - timedelta(days=1))], senior(), DAY)
    s = score_program(prog("p1", "10:00", "11:00", key=title, cast=["가수"]), profile, [])
    assert s.parts["series"] > 0


def test_excluded_genre_blocks_show_with_that_genre_among_many():
    progs = [prog("star", "20:00", "21:00", genre="트로트", genres=["트로트", "예능"])]
    p = flat_profile(series={"star": 1.0}, genre={"트로트": 1.0})
    assert [e.program_id for e in plan(progs, profile=p)] == ["star"], "규칙이 없으면 들어감"
    assert plan(progs, profile=p, rules=[rule("exclude", "예능", target_type="genre")]) == []


def test_reason_names_the_liked_genre_among_many():
    from app.engine.planner import Entry
    from app.engine.reason import make_reason

    show = prog("star", "20:00", "21:00", genre="예능", genres=["예능", "트로트"], cast=["가수"])
    scored = score_program(show, flat_profile(genre={"트로트": 1.0}), [])
    entry = Entry(
        program_id="star",
        channel_id="KBS1",
        title="star",
        start=show.start,
        end=show.end,
        score=scored.score,
        kind="pick",
        scored=scored,
        source=show,
    )
    assert make_reason(entry) == "좋아하시는 트로트 방송이에요"


def test_sample_programs_and_logs_list_all_genres_with_main_genre_first(sample_session):
    """샘플도 외부 편성표처럼 장르 목록(genres)을 갖고, 대표 장르(genre)가 맨 앞."""
    programs = sample_session.scalars(select(Program)).all()
    logs = sample_session.scalars(select(WatchLog)).all()
    for row in [*programs, *logs]:
        assert row.genres and row.genres[0] == row.genre, row
    assert any(len(p.genres) >= 2 for p in programs), "장르 2개 이상인 방송이 있어야 함"
    assert any(len(w.genres) >= 2 for w in logs if w.senior_id == "s1")


def test_genre_map_covers_every_sample_genre_with_unique_synonyms():
    """data/sample/genre_map.json (표준 장르 사전 초안): 샘플 장르는 전부 표준 이름이고, 동의어는 한 장르에만."""
    import json

    from app.models.sample import SAMPLE_DIR

    standard = json.loads((SAMPLE_DIR / "genre_map.json").read_text(encoding="utf-8"))["genres"]
    assert 10 <= len(standard) <= 15
    programs = json.loads((SAMPLE_DIR / "programs.json").read_text(encoding="utf-8"))
    lg_contents = json.loads((SAMPLE_DIR / "lg_contents.json").read_text(encoding="utf-8"))
    used = {g for p in programs for g in p["genres"]} | {c["genre"] for c in lg_contents}
    assert used <= set(standard), used - set(standard)
    synonyms = [s for g in standard.values() for s in g["synonyms"]]
    assert len(synonyms) == len(set(synonyms)), "같은 동의어가 두 장르에 있으면 안 됨"
    assert all(g["title_keywords"] is not None for g in standard.values())


# ───────── 배치 무게 = (점수 − 기준점) × 길이 ─────────


def test_several_shows_just_above_floor_cannot_push_out_a_favorite():
    """기준점(0.35)을 겨우 넘은 방송 여러 개를 합쳐도 겹치는 최애 하나를 밀어내지 못한다.
    (② 때 s1: 왕중왕 + 가족 여행이 별의 노래 새 회차를 밀어낸 일)"""
    fav = Candidate(key="star", start=at("21:00"), end=at("23:00"), score=0.865, floor=0.35)
    king = Candidate(key="king", start=at("20:00"), end=at("21:30"), score=0.806, floor=0.35)
    trip = Candidate(key="trip", start=at("21:30"), end=at("22:40"), score=0.366, floor=0.35)
    assert [c.key for c in select_best([fav, king, trip])] == ["star"]


def test_plan_weighs_by_score_above_floor():
    """점수 0.70 최애(2시간) vs 겹치는 0.40 두 개(1시간씩): 길이만 보면 두 개가 이기지만, 기준점 넘은 만큼으로 재면 최애."""
    profile = flat_profile(series={"fav": 1.0}, cast={"가수": 1.0}, genre={"교양": 1.0})
    progs = [
        prog("fav", "20:00", "22:00", cast=["가수"]),
        prog("weak1", "20:00", "21:00", cast=["가수"]),
        prog("weak2", "21:00", "22:00", cast=["가수"]),
    ]
    assert [e.program_id for e in plan(progs, profile=profile)] == ["fav"]


def test_show_scoring_exactly_at_floor_is_still_placed_when_free():
    """무게가 0 이어도(점수 = 기준점) 겹치는 게 없으면 들어간다 (첫날 기준점을 낮췄을 때 6등도 후보)."""
    edge = Candidate(key="edge", start=at("10:00"), end=at("11:00"), score=0.35, floor=0.35)
    assert [c.key for c in select_best([edge])] == ["edge"]


def test_floor_drops_to_sixth_score_when_fewer_than_six_pass_threshold():
    """기준점(0.35)을 넘는 방송이 6개도 안 되면 기준점을 6등 점수까지 낮춘다 (첫날에도 하루표가 비지 않게).
    약속 6절 규칙 5 의 예외. 6개 이상 넘으면 0.35 그대로."""
    from app.engine.planner import candidate_floor

    assert candidate_floor([0.9, 0.3, 0.2, 0.1, 0.05, 0.04, 0.01]) == 0.04
    assert candidate_floor([0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.1]) == config.THRESHOLD
    assert candidate_floor([0.2, 0.1]) == config.THRESHOLD  # 방송이 6개도 안 되면 낮추지 않음


# ───────── ②-2a 시청 시간: 시청 시간대 · 하루 시청 시간 상한 ─────────


def test_viewing_bands_are_bands_with_habit_score_over_min():
    p = flat_profile(timeslot={"아침": 0.13, "낮": 0.79, "저녁": 0.91, "밤": 0.43})
    assert p.viewing_bands() == {"낮", "저녁", "밤"}
    assert flat_profile().viewing_bands() == {"아침", "낮", "저녁", "밤"}, "습관 정보가 없으면 제한 없음"


def test_daily_budget_is_recent_average_or_240_when_few_days():
    from app.engine.preference import daily_budget_min

    seven_days = [log("a", DAY - timedelta(days=d), minutes=m) for d in range(1, 8) for m in (40, 60)]
    assert daily_budget_min(seven_days, DAY) == pytest.approx(100)
    three_days = [log("a", DAY - timedelta(days=d), minutes=100) for d in range(1, 4)]
    assert daily_budget_min(three_days, DAY) == config.DEFAULT_BUDGET_MIN == 240


def test_daily_budget_ignores_old_short_and_cancelled_logs():
    from app.engine.preference import daily_budget_min

    recent = [log("a", DAY - timedelta(days=d), minutes=100) for d in range(1, 8)]
    noise = [
        log("a", DAY - timedelta(days=20), minutes=600),  # 최근 14일 밖
        log("a", DAY - timedelta(days=1), minutes=3),  # 5분 미만
        log("a", DAY - timedelta(days=2), minutes=300, cancelled=True),  # 취소
    ]
    assert daily_budget_min(recent + noise, DAY) == pytest.approx(100)


def test_total_pick_minutes_stay_within_budget():
    """상한 120분: 1시간짜리 4개 중 점수 높은 2개만."""
    progs = [
        prog(k, f"{h}:00", f"{h + 1}:00", cast=["가수"])
        for k, h in (("a", 10), ("b", 12), ("c", 14), ("d", 16))
    ]
    profile = flat_profile(series={"a": 0.9, "b": 0.5, "c": 1.0, "d": 0.6}, cast={"가수": 1.0}, budget=120)
    picks = [e for e in plan(progs, profile=profile) if e.kind == "pick"]
    assert [e.program_id for e in picks] == ["a", "c"]
    assert sum((e.end - e.start).total_seconds() / 60 for e in picks) <= 120


def test_shows_outside_viewing_hours_are_not_picked():
    progs = [prog("morning", "07:00", "08:00"), prog("evening", "18:00", "19:00")]
    profile = flat_profile(
        series={"morning": 1, "evening": 1}, genre={"교양": 1}, timeslot={"아침": 0.1, "저녁": 0.9}
    )
    assert [e.program_id for e in plan(progs, profile=profile)] == ["evening"]


def test_pinned_show_is_kept_outside_viewing_hours_and_counts_against_budget():
    """'매일 챙겨 줘' 방송은 시청 시간대 밖이어도 넣고, 그 시간만큼 상한에서 뺀 나머지로 배치."""
    progs = [
        prog("pinned", "07:00", "08:00", key="pinned"),
        prog("long", "18:00", "19:00"),
        prog("short", "20:00", "20:30"),
    ]
    profile = flat_profile(
        series={"long": 1.0, "short": 1.0},
        genre={"교양": 1},
        timeslot={"아침": 0.1, "저녁": 0.9, "밤": 0.9},
        budget=90,
    )
    entries = plan(progs, profile=profile, rules=[rule("pin", "pinned")])
    assert [e.program_id for e in entries if e.kind == "pick"] == ["pinned", "short"]


def test_lg_fill_only_inside_viewing_hours():
    """방송 사이 빈 시간이 시청 시간대 밖(낮)에서 시작하면 LG 콘텐츠로 채우지 않는다."""
    progs = [prog("am", "08:00", "09:00"), prog("pm", "19:00", "20:00")]
    profile = flat_profile(
        series={"am": 1, "pm": 1}, genre={"교양": 1}, timeslot={"아침": 0.9, "낮": 0.1, "저녁": 0.9}
    )
    entries = plan(progs, profile=profile, s=senior(wake="08:00"), lgs=[lg("x", "교양", 30)])
    assert [e.kind for e in entries] == ["pick", "pick"]


def test_morning_gap_outside_viewing_hours_stays_empty():
    """기상(06:00)이 시청 시간대(아침) 밖이면 기상~첫 방송 사이도 채우지 않는다."""
    progs = [prog("noon", "12:00", "13:00")]
    profile = flat_profile(series={"noon": 1}, genre={"교양": 1}, timeslot={"아침": 0.1, "낮": 0.9})
    assert [e.kind for e in plan(progs, profile=profile, lgs=[lg("x", "교양", 30)])] == ["pick"]


def test_sample_s3_is_child_picked_interests_with_few_logs(sample_session):
    """샘플 s3: 자녀가 고른 관심사 2~3개 + 기록 거의 없음. 나이대 기본값(age_default)은 없다."""
    s3 = sample_session.get(Senior, "s3")
    assert s3.pref_source == "child"
    assert 2 <= len(s3.seed_prefs["genres"]) <= 3
    logs = sample_session.scalars(select(WatchLog).where(WatchLog.senior_id == "s3")).all()
    assert 0 < len(logs) < 10
    assert {s.pref_source for s in sample_session.scalars(select(Senior))} <= {"child", "self", "none"}
