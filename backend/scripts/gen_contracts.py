"""Pydantic 모델 → contracts/ 폴더의 스키마 파일 생성.

실행: (backend 폴더에서) uv run python scripts/gen_contracts.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.contracts.ws import WsContract
from app.main import app

out = ROOT / "contracts"
out.mkdir(exist_ok=True)

(out / "openapi.json").write_text(
    json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
(out / "ws-events.schema.json").write_text(
    json.dumps(WsContract.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print("contracts/openapi.json, contracts/ws-events.schema.json 생성 완료")
