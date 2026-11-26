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
