"""기억 저장소 (SQLite 파일 하나).

- messages: 주고받은 대화 원문
- memory_cards: "딸 이름은 지은"처럼 짧게 정리된 기억. v1은 통째로 프롬프트에 넣음(200개 이내).
  (밤마다 Claude가 대화를 카드로 정리하는 건 다음 단계)
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ..llm.base import Message, Role

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    text TEXT NOT NULL,
    fallback INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class MemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add_message(self, role: Role, text: str, fallback: bool = False) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO messages (role, text, fallback, created_at) VALUES (?, ?, ?, ?)",
                (role, text, int(fallback), _now()),
            )

    def recent_messages(self, limit: int = 20) -> list[Message]:
        """최근 대화 limit 개를 오래된 것부터."""
        with self._conn() as c:
            rows = c.execute("SELECT role, text FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [Message(role, text) for role, text in reversed(rows)]

    def add_card(self, text: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO memory_cards (text, created_at) VALUES (?, ?)", (text, _now()))

    def cards(self, limit: int = 200) -> list[str]:
        with self._conn() as c:
            rows = c.execute("SELECT text FROM memory_cards ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [t for (t,) in reversed(rows)]
