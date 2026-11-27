"""엔진 보강 ②-4 (배치·채우기): 긴 빈 시간 채우는 순서, 점수 비슷하면 지금 채널, 이미 시작한 방송, 하루표 변경 기록."""

from datetime import date, datetime, timedelta

from app.engine.planner import build_plan
from app.engine.preference import Profile
from app.engine.rules import RuleSet
from app.models.db import LgContent, Program, Senior

DAY = date(2026, 12, 1)
ALL_ON = {h: 1.0 for h in range(24)}


def at(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(DAY.year, DAY.month, DAY.day) + timedelta(hours=h, minutes=m)


def prog(pid, start, end, key=None, genre="교양", cast=(), ch="KBS1", episode=None):
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
        cast_roles={},
        episode=episode,
        is_new=False,
        is_live=False,
    )


def senior():
    return Senior(
        id="t",
        name="테스트",
        age=75,
        wake_time="06:00",
        sleep_time="22:00",
        pref_source="child",
        seed_prefs={"series": [], "cast": [], "genres": []},
        family_picks=[],
        fixed_breaks=[],
    )


def profile(series=None, cast=None, genre=None, timeslot=None, budget=600.0, focus=60.0):
    return Profile(
        series=series or {},
        cast=cast or {},
        genre=genre or {},
        timeslot=timeslot or {},
        history_share=0.0,
        n_logs=0,
        daily_budget_min=budget,
        focus_budget_min=focus,
        on_ratio=dict(ALL_ON),
        genre_seen_share={
            g: 1.0
            for g in (
                "교양",
                "다큐",
                "건강",
                "요리",
                "드라마",
                "사극",
                "영화",
                "트로트",
                "예능",
                "뉴스",
                "시사",
            )
        },
    )


def gap_items(p):
    return [(e.program_id, e.kind) for e in p.entries if e.kind != "pick"]


def test_long_gap_prefers_another_episode_of_a_planned_series():
    """긴 빈 시간 1순위: 하루표에 있는 시리즈의 다른 회차 (예: 2회 연속 방송)."""
    progs = [
        prog("ep1", "10:00", "11:00", key="d", episode="1", cast=["주연"]),
        prog("ep2", "11:00", "12:00", key="d", episode="2", cast=["주연"], ch="MBC"),
        prog("cast", "11:00", "12:00", key="c", cast=["좋아하는 가수"], ch="SBS"),
        prog("end", "12:00", "13:00", key="e", cast=["주연"]),
    ]
    prof = profile(series={"d": 1.0, "e": 1.0}, cast={"주연": 1.0, "좋아하는 가수": 1.0}, focus=120)
    p = build_plan(progs, [], senior(), prof, RuleSet([], DAY), DAY)
    assert ("ep2", "fill") in gap_items(p)


def test_long_gap_order_is_cast_then_genre_then_habit_then_lg():
    progs = [
        prog("a", "10:00", "11:00", key="a", cast=["x"]),
        prog("b", "13:00", "14:00", key="b", cast=["x"], ch="MBC"),
        prog("genre-only", "11:00", "12:00", genre="다큐", ch="SBS"),
        prog("cast-match", "11:00", "12:00", cast=["좋아하는 가수"], ch="EBS1"),
    ]
    prof = profile(
        series={"a": 1.0, "b": 1.0}, cast={"x": 1.0, "좋아하는 가수": 1.0}, genre={"다큐": 1.0}, focus=120
    )
    p = build_plan(progs, [], senior(), prof, RuleSet([], DAY), DAY)
    first_fill = next(e for e in p.entries if e.kind != "pick")
    assert first_fill.program_id == "cast-match" and first_fill.reason == "좋아하는 가수 님이 나와요"


def test_similar_score_prefers_the_current_channel():
    """점수 차 0.1 이내면 지금 채널의 다음 방송 (채널 전환 줄이기)."""
    progs = [
        prog("now", "10:00", "11:00", key="now", cast=["x"], ch="KBS1"),
        prog("same-ch", "11:00", "12:00", key="s", genre="다큐", ch="KBS1"),
        prog(
            "other-ch", "11:00", "12:00", key="o", genre="교양", ch="MBC"
        ),  # 같은 '장르' 순서, 점수만 조금 높음
        prog("end", "12:00", "13:00", key="end", cast=["x"], ch="SBS"),
    ]
    prof = profile(
        series={"now": 1.0, "end": 1.0}, cast={"x": 1.0}, genre={"다큐": 0.9, "교양": 1.0}, focus=120
    )
    p = build_plan(progs, [], senior(), prof, RuleSet([], DAY), DAY)
    assert next(e for e in p.entries if e.kind != "pick").program_id == "same-ch"


def test_already_started_show_needs_half_and_15_minutes_left():
    """빈 시간이 10:40 에 시작: 10:00~11:00 방송(남은 20분 < 절반 30분)은 안 넣고, 10:30~12:00(남은 80분 ≥ 절반)은 넣음."""
    progs = [
        prog("first", "10:00", "10:40", key="f", cast=["x"], ch="SBS"),
        prog("short-left", "10:00", "11:00", key="sl", cast=["좋아하는 가수"], ch="KBS1"),
        prog("long-left", "10:30", "12:00", key="ll", cast=["좋아하는 가수"], ch="MBC"),
        prog("last", "12:00", "13:00", key="l", cast=["x"], ch="SBS"),
    ]
    prof = profile(series={"f": 1.0, "l": 1.0}, cast={"x": 1.0, "좋아하는 가수": 1.0}, focus=100)
    p = build_plan(progs, [], senior(), prof, RuleSet([], DAY), DAY)
    ids = [e.program_id for e in p.entries]
    assert "short-left" not in ids and "long-left" in ids


def test_lg_fill_must_pass_taste_floor_and_comes_after_program_categories():
    progs = [
        prog("a", "10:00", "11:00", key="a", cast=["x"]),
        prog("b", "13:00", "14:00", key="b", cast=["x"], ch="MBC"),
    ]
    lg = [
        LgContent(id="lg", title="lg", genre="교양", cast=["x"], duration_min=40, source="LG채널")
    ]  # LG 30% 안
    prof = profile(series={"a": 1.0, "b": 1.0}, cast={"x": 1.0}, genre={"교양": 1.0}, focus=120)
    p = build_plan(progs, lg, senior(), prof, RuleSet([], DAY), DAY)
    assert ("lg", "lg") in gap_items(p), "맞는 방송이 없으면 취향 하한을 넘는 LG"


def test_version_records_a_changed_slot_even_with_the_same_program(tmp_path):
    """같은 방송이 10시 pick → 11시 fill 로 바뀌어도 '바뀜'으로 새 버전 (Codex 리뷰에서 찾음)."""
    from app.engine.plan import Entry, Plan
    from app.engine.service import record_version, save_and_respond
    from app.models.db import PlanVersion, init_db, make_engine, make_session_factory
    from app.models.sample import load_sample

    engine = make_engine(tmp_path / "v.db")
    init_db(engine)
    with make_session_factory(engine)() as session:
        load_sample(session)
        p = prog("x", "10:00", "11:00")

        def one(kind, start, end):
            e = Entry("x", "KBS1", "x", at(start), at(end), 0.5, kind, source=p, reason="이유")
            return Plan(entries=[e], floor=0.35, budget_min=240, hours=set(), knows_taste=True, day=DAY)

        save_and_respond(session, "s1", DAY, one("pick", "10:00", "11:00"))
        save_and_respond(session, "s1", DAY, one("fill", "11:00", "11:30"))
        versions = session.query(PlanVersion).filter_by(senior_id="s1").order_by(PlanVersion.version).all()
        assert [v.version for v in versions] == [1, 2]
        assert versions[-1].changes[0]["change"] == "바뀜"
        assert record_version(session, "s1", DAY, one("fill", "11:00", "11:30"), "같음") is None
    engine.dispose()


def test_gap_search_moves_on_to_shows_that_start_later():
    """'높음' 10:00~12:00 빈 시간에 10:00 엔 맞는 방송이 없어도, 10:30 에 시작하는 좋아하는 출연자 방송은 넣는다 (Codex)."""
    progs = [
        prog("a", "09:00", "10:00", key="a", cast=["x"]),
        prog("liked", "10:30", "11:30", key="l", cast=["좋아하는 가수"], ch="MBC"),
        prog("b", "12:00", "13:00", key="b", cast=["x"], ch="SBS"),
    ]
    prof = profile(series={"a": 1.0, "b": 1.0}, cast={"x": 1.0, "좋아하는 가수": 1.0}, focus=120)
    p = build_plan(progs, [], senior(), prof, RuleSet([], DAY), DAY)
    assert ("liked", "fill") in gap_items(p)


def test_version_records_an_end_time_change(tmp_path):
    from app.engine.plan import Entry, Plan
    from app.engine.service import record_version, save_and_respond
    from app.models.db import init_db, make_engine, make_session_factory
    from app.models.sample import load_sample

    engine = make_engine(tmp_path / "e.db")
    init_db(engine)
    with make_session_factory(engine)() as session:
        load_sample(session)
        p = prog("x", "10:00", "11:00")

        def one(end):
            e = Entry("x", "KBS1", "x", at("10:00"), at(end), 0.5, "fill", source=p, reason="이유")
            return Plan(entries=[e], floor=0.35, budget_min=240, hours=set(), knows_taste=True, day=DAY)

        save_and_respond(session, "s1", DAY, one("11:00"))
        assert record_version(session, "s1", DAY, one("10:45"), "끝 바뀜") is not None
    engine.dispose()
