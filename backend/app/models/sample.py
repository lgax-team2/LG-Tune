"""공통 샘플(data/sample/*.json)을 DB에 넣는다. 각자 개발·테스트·시연을 같은 데이터로 하기 위함."""

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from .db import Channel, LgContent, Program, Senior, UserRule, WatchLog

SAMPLE_DIR = Path(__file__).resolve().parents[3] / "data" / "sample"


def _read(name: str, sample_dir: Path) -> list | dict:
    return json.loads((sample_dir / name).read_text(encoding="utf-8"))


def load_sample(session: Session, sample_dir: Path = SAMPLE_DIR) -> dict[str, int]:
    """비어 있는 DB에 샘플을 넣고, 표별로 몇 줄 넣었는지 돌려준다."""
    channels = [Channel(**c) for c in _read("channels.json", sample_dir)]
    programs = [
        Program(**{**p, "start": datetime.fromisoformat(p["start"]), "end": datetime.fromisoformat(p["end"])})
        for p in _read("programs.json", sample_dir)
    ]
    seniors = [Senior(**s) for s in _read("seniors.json", sample_dir)]
    logs = [
        WatchLog(**{**w, "started_at": datetime.fromisoformat(w["started_at"])})
        for w in _read("watch_logs.json", sample_dir)
    ]
    lg = [LgContent(**c) for c in _read("lg_contents.json", sample_dir)]
    rules = [UserRule(**r) for r in _read("user_rules.json", sample_dir)]
    session.add_all([*channels, *programs, *seniors, *logs, *lg, *rules])
    session.commit()
    return {
        "channels": len(channels),
        "programs": len(programs),
        "seniors": len(seniors),
        "watch_logs": len(logs),
        "lg_contents": len(lg),
        "user_rules": len(rules),
    }
