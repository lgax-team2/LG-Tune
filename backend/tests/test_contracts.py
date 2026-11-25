"""계약 테스트: 시나리오 파일의 모든 줄이 계약에 맞는지, API가 계약대로 응답하는지."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app.contracts.ws import ClientEvent, ServerEvent
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
server_adapter = TypeAdapter(ServerEvent)
client_adapter = TypeAdapter(ClientEvent)


def test_scenarios_match_contract():
    files = list((ROOT / "contracts" / "scenarios").glob("*.jsonl"))
    assert files, "시나리오 파일이 하나도 없음"
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            adapter = server_adapter if row["dir"] == "server" else client_adapter
            adapter.validate_python(row["event"]), f"{f.name}:{n}"


def test_healthz():
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_plan_today_shape():
    r = TestClient(app).get("/api/plan/today")
    assert r.status_code == 200
    assert r.json()["items"][0]["reason"]


def test_ws_sends_clock_tick():
    with TestClient(app).websocket_connect("/ws") as ws:
        msg = server_adapter.validate_json(ws.receive_text())
        assert msg.type == "clock.tick"
