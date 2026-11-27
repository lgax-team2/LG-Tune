"""원본 응답 저장소: data/epg/raw/<날짜>/<출처>.json

- 받은 그대로 저장한다 (나중에 정리 규칙을 고쳐도 다시 받지 않고 재처리하려고).
- 둘 다 실패한 날은 가장 최근 저장본으로 진행한다 (pipeline.py).
- Git에 올리지 않는다: 폴더를 처음 만들 때 '*' 만 적힌 .gitignore 를 같이 만든다.
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
EPG_DIR = REPO_ROOT / "data" / "epg"
RAW_DIR = EPG_DIR / "raw"
CACHE_DIR = EPG_DIR / "cache"  # LLM 판단 결과 (enrich/judge.py)


def ensure_ignored_dir(path: Path) -> Path:
    """폴더를 만들고, 안에 .gitignore('*')를 둬서 내용이 Git에 올라가지 않게 한다."""
    path.mkdir(parents=True, exist_ok=True)
    ignore = path / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# 자동 생성: 이 폴더 내용은 Git에 올리지 않음\n*\n", encoding="utf-8")
    return path


def save_raw(day: date, source: str, payload: dict[str, Any], raw_dir: Path = RAW_DIR) -> Path:
    """원본 하나를 저장하고 파일 경로를 돌려준다."""
    ensure_ignored_dir(raw_dir)
    path = raw_dir / day.isoformat() / f"{source}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_raw(day: date, source: str, raw_dir: Path = RAW_DIR) -> dict[str, Any] | None:
    """그날 그 출처의 원본. 없으면 None."""
    path = raw_dir / day.isoformat() / f"{source}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def latest_before(day: date, raw_dir: Path = RAW_DIR) -> tuple[date, dict[str, dict[str, Any]]] | None:
    """day 보다 앞선 날 중 가장 최근 저장본 {출처: 원본}. 없으면 None.

    TODO: 전날 저장본의 날짜를 오늘로 옮겨 쓰는 규칙 (5일치라 오늘 분이 들어 있을 수 있음) 정하기.
    """
    raise NotImplementedError("전날 저장본 대체는 아직 구현 전")
