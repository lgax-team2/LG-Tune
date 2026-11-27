"""GET /api/schedules/{senior_id} 가 엔진(make_schedule) 결과를 돌려주는지.

DB 는 tmp_path 의 빈 파일로 바꿔 끼운다 → 첫 요청 때 샘플이 자동으로 들어가는지도 같이 확인된다.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.schedules import get_session, open_session
from app.main import app

BACKEND_DATA = Path(__file__).resolve().parents[1] / "data"


def _files_in_backend_data() -> set[str]:
    return {p.name for p in BACKEND_DATA.iterdir()} if BACKEND_DATA.exists() else set()


@pytest.fixture
def client(tmp_path):
    def session_on_tmp_db():
        yield from open_session(tmp_path / "t.db")

    app.dependency_overrides[get_session] = session_on_tmp_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_session, None)


@pytest.mark.parametrize("senior_id", ["s1", "s2", "s3"])
def test_known_senior_gets_engine_schedule(client, senior_id):
    r = client.get(f"/api/schedules/{senior_id}", params={"date": "2026-12-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["senior_id"] == senior_id
    assert body["items"], "샘플 편성표가 있는 날이라 항목이 있어야 함"
    assert all(i["start"].startswith("2026-12-01") for i in body["items"])


def test_unknown_senior_is_404(client):
    assert client.get("/api/schedules/s9").status_code == 404


def test_date_omitted_means_demo_day(client):
    body = client.get("/api/schedules/s1").json()
    assert body["date"] == "2026-12-01"
    assert body["items"]


def test_given_date_is_used(client):
    # 샘플 편성표는 12/1 하루치뿐 → 다른 날은 항목 없이 그 날짜로 답한다
    r = client.get("/api/schedules/s1", params={"date": "2026-12-02"})
    assert r.status_code == 200
    assert r.json() == {"senior_id": "s1", "date": "2026-12-02", "items": []}


def test_no_new_file_in_backend_data(client):
    before = _files_in_backend_data()
    client.get("/api/schedules/s1")
    client.get("/api/schedules/s9")
    assert _files_in_backend_data() == before


# ── 개발용 엔진 확인 화면: GET /api/schedules/{senior_id}/view ──

import re

from app.api.schedules import MISSED_REASONS

CONTRACTS_OPENAPI = Path(__file__).resolve().parents[2] / "contracts" / "openapi.json"


def _view_data(html: str) -> dict:
    m = re.search(r'<script id="view-data" type="application/json">(.*?)</script>', html, re.DOTALL)
    assert m, "화면에 데이터 덩어리가 들어 있어야 함"
    return json.loads(m.group(1))


@pytest.mark.parametrize("senior_id", ["s1", "s2", "s3"])
def test_view_is_html_with_engine_result(client, senior_id):
    r = client.get(f"/api/schedules/{senior_id}/view", params={"date": "2026-12-01"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<!DOCTYPE html>" in r.text
    assert "cdn" not in r.text.lower() and "<script src" not in r.text  # 외부 파일 없이 한 파일

    data = _view_data(r.text)
    api = client.get(f"/api/schedules/{senior_id}", params={"date": "2026-12-01"}).json()
    assert data["senior"]["id"] == senior_id
    assert data["date"] == "2026-12-01"
    assert [i["program_id"] for i in data["items"]] == [i["program_id"] for i in api["items"]]
    assert {s["id"] for s in data["seniors"]} >= {"s1", "s2", "s3"}
    for key in ("series", "cast", "genre", "timeslot"):
        assert len(data["profile"][key]) <= 3


def test_view_missed_top5_are_not_in_plan_and_have_reason(client):
    data = _view_data(client.get("/api/schedules/s1/view").text)
    planned = {i["program_id"] for i in data["items"]}
    missed = data["missed"]
    assert 0 < len(missed) <= 5
    assert all(m["program_id"] not in planned for m in missed)
    assert all(m["why"] in MISSED_REASONS for m in missed)
    scores = [m["score"] for m in missed]
    assert scores == sorted(scores, reverse=True)


def test_view_marks_excluded_series_as_rule(client):
    # s1 샘플 규칙: mbc-bluesea "이제 안 볼래" → 빠진 이유는 규칙
    data = _view_data(client.get("/api/schedules/s1/view", params={"limit": 100}).text)
    blue = [m for m in data["missed"] if m["series_key"] == "mbc-bluesea"]
    assert blue and all(m["why"] == "규칙으로 제외" for m in blue)


def test_view_out_of_day_reason_uses_start_time_only(client):
    """취침 전에 시작한 방송은 '기상 전·취침 후'로 빠지지 않는다 (엔진 규칙과 같은 판정)."""
    data = _view_data(client.get("/api/schedules/s1/view", params={"limit": 100}).text)
    wake, sleep = data["senior"]["wake"], data["senior"]["sleep"]
    for m in data["missed"]:
        starts_in_day = wake <= m["start"][11:16] < sleep
        assert (m["why"] == "기상 전·취침 후") == (not starts_in_day), m


def test_old_db_without_new_columns_gives_clear_message(tmp_path):
    """DB 구조가 바뀐 뒤 옛날 DB 파일을 그대로 쓰면, 이유 모를 오류 대신 'pnpm sample' 안내가 나온다."""
    import sqlite3

    first = TestClient(app)
    old_db = tmp_path / "old.db"

    def session_on_old_db():
        yield from open_session(old_db)

    app.dependency_overrides[get_session] = session_on_old_db
    try:
        assert first.get("/api/schedules/s1").status_code == 200  # 새로 만든 DB 는 정상
        with sqlite3.connect(old_db) as con:  # 예전 구조 흉내: genres 칸이 없던 때
            con.execute("ALTER TABLE programs DROP COLUMN genres")
        r = first.get("/api/schedules/s1")
        assert r.status_code == 500
        assert "pnpm sample" in r.json()["detail"] and "programs.genres" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_view_shows_budget_and_viewing_hours(client):
    """확인 화면 요약: 하루 시청 시간 상한, pick 총 시간(상한 이하), 시청 시간대."""
    data = _view_data(client.get("/api/schedules/s1/view").text)
    budget = data["budget"]
    used = sum(
        (datetime.fromisoformat(i["end"]) - datetime.fromisoformat(i["start"])).total_seconds() / 60
        for i in data["items"]
    )
    assert budget["used_min"] == round(used)
    s3 = next(g for g in data["quality"]["goals"] if g["code"] == "S3")
    if (
        used > budget["limit_min"]
    ):  # 대표 방송(S1)이 상한(S3)보다 우선이라 넘을 수 있음 → 실패로 표시하고 이유
        assert s3["ok"] is False and "상한" in s3["detail"]
    else:
        assert s3["ok"] is True
    assert data["viewing_hours"] and all(r.endswith("시") for r in data["viewing_hours"])


def test_view_marks_shows_outside_viewing_hours(client):
    """s1 은 아침(5~8시)에 TV 를 거의 안 켬 → 기상 뒤 그 시각에 시작하는 방송은 '시청 시간대 밖'."""
    data = _view_data(client.get("/api/schedules/s1/view", params={"limit": 100}).text)
    low = {int(h) for h, t in data["tiers"].items() if t == "낮음"}
    morning = [
        m
        for m in data["missed"]
        if int(m["start"][11:13]) in low
        and data["senior"]["wake"] <= m["start"][11:16] < data["senior"]["sleep"]
    ]
    assert morning and all(m["why"] in ("시청 시간대 밖", "규칙으로 제외") for m in morning)
    assert any(m["why"] == "시청 시간대 밖" for m in morning)


def test_view_unknown_senior_is_404(client):
    assert client.get("/api/schedules/s9/view").status_code == 404


def test_view_is_not_in_api_contract():
    # 화면 경로는 약속(openapi)에 안 들어감 → pnpm gen 해도 contracts 변화 없음
    assert not any(path.endswith("/view") for path in app.openapi()["paths"])
    assert json.loads(CONTRACTS_OPENAPI.read_text(encoding="utf-8")) == app.openapi()


def test_changing_interests_changes_the_next_schedule(tmp_path):
    """가족 화면에서 관심사(seed_prefs)를 바꾸면 다음 하루표에 바로 반영된다."""
    from app.models.db import Senior

    db = tmp_path / "seed.db"

    def session_on_db():
        yield from open_session(db)

    app.dependency_overrides[get_session] = session_on_db
    try:
        client = TestClient(app)
        before = client.get("/api/schedules/s3").json()["items"]
        gen = open_session(db)
        session = next(gen)
        s3 = session.get(Senior, "s3")
        s3.seed_prefs = {"series": [], "cast": [], "genres": ["스포츠", "영화"]}
        session.commit()
        gen.close()
        after = client.get("/api/schedules/s3").json()["items"]
        assert [i["program_id"] for i in after] != [i["program_id"] for i in before]
        assert any("스포츠" in i["reason"] or "영화" in i["reason"] for i in after)
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_view_data_escapes_script_tags_in_titles(client, tmp_path):
    """방송 제목에 </script> 가 섞여도 화면 데이터가 깨지지 않는다 (JSON 안의 '<' 를 이스케이프)."""
    from app.models.db import Program

    client.get("/api/schedules/s1")  # 샘플 DB 만들기
    gen = open_session(tmp_path / "t.db")
    session = next(gen)
    for p in session.query(Program).all():
        p.title = p.title + "</script><b>"
    session.commit()
    gen.close()
    html = client.get("/api/schedules/s1/view").text
    blob = html.split('<script id="view-data" type="application/json">', 1)[1].split("</script>", 1)[0]
    assert "<" not in blob, "데이터 안에 '<' 가 그대로 있으면 </script> 로 태그가 닫힐 수 있음"
    assert any("</script><b>" in i["title"] for i in json.loads(blob)["items"] if i["kind"] == "pick")


def test_view_top_shows_quality_table_and_value_metrics(client):
    """확인 화면 맨 위: 기준표 v3 의 반드시 7개·목표 9개 판정 + 가치 지표."""
    data = _view_data(client.get("/api/schedules/s1/view").text)
    assert [q["code"] for q in data["quality"]["must"]] == ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"]
    assert [q["code"] for q in data["quality"]["goals"]] == [
        "S1",
        "S2",
        "S3",
        "S9",
        "S10",
        "S8",
        "S4",
        "S5",
        "S6",
    ]
    assert all(q["ok"] is True for q in data["quality"]["must"]), data["quality"]["must"]
    m = data["metrics"]
    assert {
        "taste_match",
        "new_genre",
        "lg_minutes",
        "lg_share",
        "genre_share_with_rep",
        "genre_share_without_rep",
    } <= set(m)
    assert data["hint"] == "" and set(data["roles"].values()) <= {
        "normal",
        "pin",
        "representative",
        "novelty",
        "background",
    }


def test_view_lists_paused_series_and_unpause_brings_it_back(client):
    """확인 화면: 반복 거절로 '쉬어가는 중'인 시리즈 목록 + 되돌리기(개발용 POST) 하면 다음 계산부터 다시 후보."""
    data = _view_data(client.get("/api/schedules/s1/view").text)
    paused = data["paused"]
    assert paused and all({"series_key", "title", "until"} <= set(p) for p in paused)
    key = paused[0]["series_key"]
    r = client.post("/api/schedules/s1/unpause", params={"series": key})
    assert r.status_code == 200
    again = _view_data(client.get("/api/schedules/s1/view").text)
    assert key not in [p["series_key"] for p in again["paused"]]
    assert data["fixed_breaks"] == ["12:00-12:30"]
    assert not any(path.endswith("/unpause") for path in app.openapi()["paths"]), (
        "개발용이라 약속(openapi) 밖"
    )


def test_plan_versions_are_saved_only_when_the_plan_changes(client, tmp_path):
    """하루표가 다시 만들어질 때 바뀐 칸이 있을 때만 새 버전 + 바뀐 칸·이유를 저장, 확인 화면에 '변경 기록'."""
    from app.models.db import PlanVersion, UserRule

    client.get("/api/schedules/s1")
    client.get("/api/schedules/s1")  # 같은 하루표 → 새 버전 없음
    gen = open_session(tmp_path / "t.db")
    session = next(gen)
    versions = session.query(PlanVersion).filter_by(senior_id="s1").all()
    assert [v.version for v in versions] == [1]
    first_pick = client.get("/api/schedules/s1").json()["items"]
    target = next(i for i in first_pick if i["kind"] == "pick")
    series = session.get(
        __import__("app.models.db", fromlist=["Program"]).Program, target["program_id"]
    ).series_key
    session.add(UserRule(senior_id="s1", kind="exclude", target_type="series", target=series))
    session.commit()
    gen.close()
    client.get("/api/schedules/s1")
    data = _view_data(client.get("/api/schedules/s1/view").text)
    latest = data["versions"][0]
    assert latest["version"] == 2
    removed = [c for c in latest["changes"] if c["change"] == "빠짐"]
    assert any(c["program_id"] == target["program_id"] and c["why"] == "규칙으로 제외" for c in removed)
