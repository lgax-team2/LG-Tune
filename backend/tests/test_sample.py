"""공통 샘플·DB 구조 테스트: 샘플이 약속(docs/약속.md)대로 생겼는지, DB에 잘 들어가는지."""

import json
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import pairwise

import pytest
from sqlalchemy import func, select

from app.models.db import Channel, Program, Senior, WatchLog, init_db, make_engine, make_session_factory
from app.models.sample import SAMPLE_DIR, load_sample


def read(name):
    return json.loads((SAMPLE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def session(tmp_path):
    engine = make_engine(tmp_path / "t.db")
    init_db(engine)
    with make_session_factory(engine)() as s:
        yield s


def test_sample_loads_into_db(session):
    counts = load_sample(session)
    assert counts["seniors"] == 3
    assert session.scalar(select(func.count()).select_from(Program)) == counts["programs"]
    assert session.get(Channel, "KBS1").number == 9
    assert session.get(Senior, "s1").seed_prefs["genres"] == ["트로트", "드라마"]
    log = session.scalars(select(WatchLog).limit(1)).one()
    assert isinstance(log.started_at, datetime)


def test_each_channel_fills_the_day_without_gaps_or_overlaps():
    by_ch = defaultdict(list)
    for p in read("programs.json"):
        by_ch[p["channel_id"]].append((datetime.fromisoformat(p["start"]), datetime.fromisoformat(p["end"])))
    assert set(by_ch) == {c["id"] for c in read("channels.json")}
    for ch, slots in by_ch.items():
        slots.sort()
        assert slots[0][0].hour == 5, ch
        assert slots[-1][1] == slots[0][0].replace(hour=0) + timedelta(days=1), ch
        for (_, end), (nxt, _) in pairwise(slots):
            assert end == nxt, f"{ch} {end} 빈틈/겹침"


def test_watch_logs_cover_two_weeks_before_demo_day_and_include_edge_cases():
    logs = read("watch_logs.json")
    days = {w["started_at"][:10] for w in logs}
    assert min(days) == "2026-11-17" and max(days) == "2026-11-30"
    assert any(w["watched_min"] < 5 and w["feedback"] == "none" for w in logs), "5분 미만 기록 필요"
    assert {w["feedback"] for w in logs} >= {"none", "next", "help"}
    per_senior = defaultdict(int)
    for w in logs:
        per_senior[w["senior_id"]] += 1
    assert per_senior["s3"] < per_senior["s1"] / 5, "s3 는 기록이 적은 콜드 스타트"


def test_every_log_matches_a_known_series():
    keys = {p["series_key"] for p in read("programs.json")}
    assert all(w["series_key"] in keys for w in read("watch_logs.json"))


def test_schedule_example_points_to_real_programs_without_overlap():
    progs = {p["id"]: p for p in read("programs.json")}
    ex = read("schedule_example.json")
    items = ex["items"]
    assert all(i["program_id"] in progs for i in items)
    for a, b in pairwise(items):
        assert a["end"] <= b["start"]
    s1 = next(s for s in read("seniors.json") if s["id"] == ex["senior_id"])
    assert items[-1]["end"][11:16] <= s1["sleep_time"], "취침 시간 전에 끝나야 함"
    assert items[0]["start"][11:16] >= s1["wake_time"]


def test_schedule_api_returns_example_in_contract_shape():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    r = client.get("/api/schedules/s1", params={"date": "2026-12-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["items"][0]["reason"]
    assert {i["kind"] for i in body["items"]} <= {"pick", "fill"}
    assert client.get("/api/schedules/s9").status_code == 404
