"""엔진 보강 ②-3 (신호): 종료 이유·회차·출연자 역할·고정 비움 시간·반복 거절 쉬어가기·1시간 단위 시간대 습관."""

from datetime import date, datetime, timedelta

import pytest

from app.engine import config
from app.engine.planner import build_plan
from app.engine.preference import Profile, build_profile
from app.engine.rules import RuleSet
from app.engine.scoring import score_program
from app.models.db import Program, Senior, UserRule, WatchLog

DAY = date(2026, 12, 1)


def at(hhmm: str, d: date = DAY) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day) + timedelta(hours=h, minutes=m)


def prog(pid, start, end, key=None, genre="교양", cast=("가수",), ch="KBS1", roles=None, episode=None):
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
        cast_roles=roles or {},
        episode=episode,
        is_new=False,
        is_live=False,
    )


def senior(breaks=(), genres=()):
    return Senior(
        id="t",
        name="테스트",
        age=75,
        wake_time="06:00",
        sleep_time="22:00",
        pref_source="child",
        seed_prefs={"series": [], "cast": [], "genres": list(genres)},
        family_picks=[],
        fixed_breaks=list(breaks),
    )


def log(key, days_ago, end_reason="completed", minutes=60.0, hhmm="20:00", how="chosen", cast=()):
    return WatchLog(
        senior_id="t",
        channel_id="KBS1",
        series_key=key,
        genre="교양",
        genres=["교양"],
        cast=list(cast),
        started_at=at(hhmm, DAY - timedelta(days=days_ago)),
        watched_min=minutes,
        feedback="none",
        how_started=how,
        cancelled=False,
        end_reason=end_reason,
    )


def flat(series=None, cast=None, genre=None, timeslot=None):
    return Profile(
        series=series or {},
        cast=cast or {},
        genre=genre or {},
        timeslot=timeslot or {},
        history_share=0.0,
        n_logs=0,
        on_ratio={h: 1.0 for h in range(24)},
    )


def plan(progs, prof, s=None, rules=()):
    return build_plan(progs, [], s or senior(), prof, RuleSet(list(rules), DAY), DAY)


# ───────── 종료 이유: 시리즈 점수 = 신호 세기 × 완주 추정 가중치 × 반감기 ─────────


def test_series_taste_weighs_how_the_show_ended():
    finished = [log("done", d, "completed") for d in range(1, 8)]
    skipped = [log("skip", d, "skipped", hhmm="19:00") for d in range(1, 8)]
    p = build_profile(finished + skipped, senior(), DAY)
    expected = config.END_REASON_WEIGHT["skipped"] / config.END_REASON_WEIGHT["completed"]
    assert p.series["skip"] / p.series["done"] == pytest.approx(expected)


def test_old_logs_without_end_reason_count_as_completed():
    old = log("x", 1)
    old.end_reason = None
    assert build_profile([old], senior(), DAY).series["x"] > 0


# ───────── 출연자 역할 ─────────


def test_cast_role_scales_the_cast_score():
    prof = flat(cast={"가수": 1.0})
    weights = {}
    for role in ("host", "lead", "regular", "guest", None):
        roles = {"가수": role} if role else {}
        weights[role] = score_program(prog("x", "20:00", "21:00", roles=roles), prof, []).parts["cast"]
    assert weights["host"] == weights["lead"] == weights[None] == pytest.approx(0.25)
    assert weights["regular"] == pytest.approx(0.25 * 0.6) and weights["guest"] == pytest.approx(0.25 * 0.3)


# ───────── 고정 비움 시간 (식사·약) ─────────


def test_nothing_starts_inside_fixed_breaks():
    progs = [
        prog("lunch", "12:00", "13:00"),
        prog("before", "11:00", "12:00", ch="MBC"),
        prog("after", "13:00", "14:00"),
    ]
    p = plan(
        progs, flat(series={k: 1.0 for k in ("lunch", "before", "after")}), s=senior(breaks=["12:00-12:30"])
    )
    assert "lunch" not in [e.program_id for e in p.entries]
    assert p.dropped["lunch"] == "고정 비움 시간"


# ───────── 반복 거절 → 7일 쉬어가기 ─────────


def test_three_rejections_in_14_days_pause_the_series_for_7_days():
    logs = [log("meh", d, "skipped", minutes=3) for d in (10, 6, 3)] + [log("meh2", 2, "completed")]
    prof = build_profile(logs, senior(), DAY)
    assert prof.paused == {"meh": DAY - timedelta(days=3) + timedelta(days=7)}  # 세 번째 거절부터 7일
    p = plan([prog("m", "20:00", "21:00", key="meh")], prof)
    assert not p.entries and p.dropped["m"] == "쉬어가는 중"


def test_pause_keeps_cast_taste_and_expires_after_7_days():
    logs = [log("meh", d, "help_cancel", cast=["배우"]) for d in (13, 12, 11)]
    prof = build_profile(logs, senior(), DAY)
    assert not prof.paused, "세 번째 거절(11일 전)부터 7일이 지나 쉬어가기 끝"
    assert prof.cast.get("배우", 0) > 0, "출연자 점수는 깎지 않음"


def test_unpause_lifts_the_current_pause_and_old_rejections_do_not_restart_it():
    logs = [log("meh", d, "skipped", minutes=3) for d in (5, 4, 3)]
    unpause = UserRule(
        senior_id="t",
        kind="unpause",
        target_type="series",
        target="meh",
        date=(DAY - timedelta(days=1)).isoformat(),
        active=True,
    )
    prof = build_profile(logs, senior(), DAY, rules=[unpause])
    assert not prof.paused


def test_cancelled_logs_do_not_count_as_rejections():
    logs = [log("meh", d, "skipped", minutes=3) for d in (5, 4, 3)]
    logs[0].cancelled = True
    assert not build_profile(logs, senior(), DAY).paused


# ───────── 시간대 습관 1시간 단위 ─────────


def test_timeslot_habit_uses_the_hour_when_there_is_enough_record():
    """20시에 매일 보면 20시 값, 기록이 거의 없는 21시는 4구간(밤) 값으로 대체."""
    logs = [log("x", d, hhmm="20:00") for d in range(1, 8)] + [log("y", 1, hhmm="21:00")]
    p = build_profile(logs, senior(), DAY)
    assert p.timeslot_score(at("20:10")) == pytest.approx(p.timeslot_hour[20])
    assert p.timeslot_score(at("21:10")) == pytest.approx(p.timeslot["밤"])


def test_episode_unknown_clashes_with_any_episode_of_the_series():
    """회차를 모르는 편은 같은 시리즈의 어떤 회차와도 겹치는 것으로 봄 (Codex 리뷰에서 찾음)."""
    from app.engine.quality import evaluate

    known = prog("k", "10:00", "11:00", key="d", episode="11")
    unknown = prog("u", "15:00", "16:00", key="d", ch="MBC")
    prof = flat(series={"d": 1.0}, cast={"가수": 1.0})
    p = plan([known, unknown], prof)
    assert len([e for e in p.entries if e.kind == "pick"]) == 1
    both = build_plan([known], [], senior(), prof, RuleSet([], DAY), DAY)
    both.entries += build_plan([unknown], [], senior(), prof, RuleSet([], DAY), DAY).entries
    assert (
        not evaluate(both, programs=[known, unknown], senior=senior(), profile=prof, rules=RuleSet([], DAY))
        .must["M4"]
        .ok
    )


def test_m2_does_not_require_pins_inside_fixed_breaks():
    from app.engine.quality import check_plan

    pinned = prog("p", "12:00", "13:00", key="p")
    pin = UserRule(senior_id="t", kind="pin", target_type="series", target="p", active=True)
    p, report = check_plan([pinned], [], senior(breaks=["12:00-12:30"]), flat(), RuleSet([pin], DAY), DAY)
    assert not p.entries and report.must["M2"].ok and report.must["M3"].ok


def test_pause_lasts_full_7_days_even_if_early_rejections_leave_the_14_day_window():
    """11/16·11/17·11/26 거절 → 11/26 부터 12/3 까지 쉼. 12/1 에 11/16 이 14일 밖이어도 계속 쉼 (Codex 리뷰에서 찾음)."""
    logs = [log("meh", d, "skipped", minutes=3) for d in (15, 14, 5)]
    assert build_profile(logs, senior(), DAY).paused == {"meh": date(2026, 12, 3)}


def test_pause_grouping_does_not_depend_on_where_history_is_cut():
    """11/7·11/8·11/11 → 쉼, 11/16·11/17·11/26 → 다시 쉼(12/3 까지). 오래된 기록을 잘라도 묶음이 바뀌면 안 됨."""
    days_ago = [(DAY - date(2026, 11, d)).days for d in (7, 8, 11, 16, 17, 26)]
    logs = [log("meh", n, "skipped", minutes=3) for n in days_ago]
    assert build_profile(logs, senior(), DAY).paused == {"meh": date(2026, 12, 3)}
