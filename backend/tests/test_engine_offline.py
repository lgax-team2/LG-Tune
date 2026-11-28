"""개인화 오프라인 평가 (app/engine/offline_eval.py) — 빠른 것만 (사람 수 적게).

기준 수치는 아직 정하지 않음 (11/28: 결과를 보고 사람이 정함). 여기서는 방향만 본다:
엔진이 (같은 칸 수의) 기준선보다 나은가 / 바뀐 취향을 따라가나 / 기록이 늘어도 나빠지지 않나 / 같은 seed = 같은 결과.
"""

from collections import defaultdict

import pytest

from app.engine import offline_eval as oe
from app.engine.sim import make_population, make_schedule


def _hit_rates(kind: str, n: int, history_days=(21,)) -> dict:
    return oe.run(n, seed=7, history_days=history_days, types=[kind], workers=1)[kind]


@pytest.mark.xfail(
    strict=True,
    reason="E-eval2b(11/28): 같은 칸 수로 맞춰도 엔진 적중이 ①자른 것보다 조금 낮음 (4명 31% vs 32%) — 기준은 사람이 정함",
)
def test_engine_beats_both_baselines_at_equal_slot_count_for_clear_taste():
    """공정 비교 (E-eval2b): 기준선 ①은 날마다 엔진과 같은 칸 수로 자른 것. 칸 수가 같으니 적중률·정밀도 둘 다 비교."""
    s = _hit_rates("뚜렷한 취향", 4)
    e, trunc, seed_only = s["engine"], s["usual_trunc"], s["seed_only"]
    assert e["hit_rate"] > trunc["hit_rate"] and e["precision"] > trunc["precision"], s
    assert e["hit_rate"] > seed_only["hit_rate"], s


def test_plan_follows_the_changed_taste():
    """'취향 바뀜'(15일째부터 다른 취향): 22~28일 하루표 방송의 장르 1위가 바뀐 취향 쪽."""
    schedule = make_schedule()
    sims = make_population(2, seed=7, schedule=schedule, types=["취향 바뀜"])
    session = oe.build_db(sims, schedule, (21,))
    by_id = {p.id: p for p in schedule}
    for sim in sims:
        minutes = defaultdict(float)
        for day in oe.EVAL_DAYS:
            planned, _ = oe.engine_plan(session, f"{sim.senior.id}@21", day)
            for pid in planned:
                p = by_id[pid]
                minutes[p.genre] += (p.end - p.start).total_seconds() / 60
        top = max(minutes, key=lambda g: (minutes[g], g))
        new, old = sim.taste.genres_on(22), sim.taste.genres_on(1)
        assert new[top] > old[top], (sim.senior.id, top, dict(minutes))
    session.close()


def test_hit_rate_with_full_history_is_not_below_three_days():
    """공정 비교 (E-eval2b): 사람 수가 적으면 중간 구간(7→14일)은 흔들리므로 양 끝(3일 vs 21일)만 비교."""
    curve = _hit_rates("뚜렷한 취향", 4, history_days=(3, 21))["curve"]
    assert curve[21] >= curve[3], curve


def test_usual_channel_baseline_is_cut_in_most_watched_hour_order():
    from datetime import datetime

    from app.models.db import Program, WatchLog

    def prog(pid, ch, hour):
        start = datetime(2026, 12, 22, hour)
        return Program(id=pid, channel_id=ch, title=pid, series_key=pid, genre="교양", genres=["교양"],
                       start=start, end=start.replace(minute=50), cast=[])  # fmt: skip

    def log(ch, hour, minutes):
        return WatchLog(senior_id="x", channel_id=ch, series_key="k", genre="교양", genres=["교양"], cast=[],
                        started_at=datetime(2026, 12, 1, hour), watched_min=minutes, how_started="chosen")  # fmt: skip

    logs = [log("KBS1", 9, 30), log("MBC", 20, 120), log("SBS", 12, 60), log("KBS1", 20, 10)]
    progs = [prog("a", "KBS1", 9), prog("b", "MBC", 20), prog("c", "SBS", 12), prog("d", "KBS1", 20)]
    assert oe.usual_channel_ranked(logs, progs) == ["b", "c", "a"], (
        "20시 MBC 120분 > 12시 SBS 60분 > 9시 KBS1"
    )


def test_top2_overlap():
    truth = {"트로트": 0.5, "사극": 0.3, "뉴스": 0.2}
    assert oe.top2_overlap({"사극": 1.0, "트로트": 0.9, "뉴스": 0.1}, truth) == 1.0
    assert oe.top2_overlap({"사극": 1.0, "뉴스": 0.9}, truth) == 0.5
    assert oe.top2_overlap({}, truth) is None


def test_channel_loyalty_changes_only_behavior_not_the_person():
    schedule = make_schedule()
    high, low = (make_population(3, seed=5, schedule=schedule, loyalty=x) for x in ("높음", "낮음"))
    assert [s.taste for s in high] == [s.taste for s in low]
    assert all(h.behavior.stickiness > lo.behavior.stickiness for h, lo in zip(high, low, strict=True))


def test_same_seed_same_result():
    schedule = make_schedule()
    a, b = (make_population(2, seed=3, schedule=schedule) for _ in range(2))
    fingerprint = lambda sims: [
        (w.series_key, w.started_at, w.watched_min, w.how_started) for s in sims for w in s.logs
    ]
    assert fingerprint(a) == fingerprint(b)
    assert oe.run(2, seed=3, history_days=(21,), workers=1) == oe.run(
        2, seed=3, history_days=(21,), workers=1
    )
