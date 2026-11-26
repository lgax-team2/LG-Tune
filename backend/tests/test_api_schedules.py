"""GET /api/schedules/{senior_id} 가 엔진(make_schedule) 결과를 돌려주는지.

DB 는 tmp_path 의 빈 파일로 바꿔 끼운다 → 첫 요청 때 샘플이 자동으로 들어가는지도 같이 확인된다.
"""

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

import json
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


def test_view_unknown_senior_is_404(client):
    assert client.get("/api/schedules/s9/view").status_code == 404


def test_view_is_not_in_api_contract():
    # 화면 경로는 약속(openapi)에 안 들어감 → pnpm gen 해도 contracts 변화 없음
    assert not any(path.endswith("/view") for path in app.openapi()["paths"])
    assert json.loads(CONTRACTS_OPENAPI.read_text(encoding="utf-8")) == app.openapi()
