"""출처마다 다른 원본 → 공통 모양(ProgramDraft).

- U+ 는 시작 시각만 있음 → 끝 = 같은 채널 다음 방송의 시작 (마지막 방송은 day_end)
- 장르는 data/sample/genre_map.json 의 표준 장르로 바꾼다
  (1) 장르 이름이 동의어 중 하나면 그 표준 장르 (2) 아니면 제목 키워드로 추정 (3) 그래도 없으면 "기타"
- series_key(회차 묶음)는 제목에서 회차 표기를 떼어 만든다. 규칙으로 안 되면 enrich/judge.py (LLM)
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

from .raw_store import REPO_ROOT

GENRE_MAP_PATH = REPO_ROOT / "data" / "sample" / "genre_map.json"
UNKNOWN_GENRE = "기타"


@dataclass
class ChannelDraft:
    id: str
    number: int  # U+ 채널 번호 (리모컨 번호)
    name: str


@dataclass
class ProgramDraft:
    """DB programs 표에 넣기 전 공통 모양. 칸 이름은 models/db.py Program 과 같게."""

    channel_id: str
    title: str
    start: datetime
    end: datetime
    genres: list[str] = field(default_factory=list)  # 표준 장르, 첫 번째가 대표 장르
    cast: list[str] = field(default_factory=list)
    is_new: bool = False
    is_live: bool = False
    series_key: str = ""
    source: str = ""  # 어느 출처에서 왔는지 (uplus / skylife)

    @property
    def id(self) -> str:
        return f"{self.channel_id}-{self.start:%Y%m%d-%H%M}"


@cache
def _genre_map(path: Path = GENRE_MAP_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))["genres"]


def to_standard_genre(raw_genre: str | None, title: str) -> str:
    """외부 장르 이름(+제목) → 표준 장르 1개."""
    gmap = _genre_map()
    if raw_genre:
        for std, rule in gmap.items():
            if raw_genre.strip().lower() in (s.lower() for s in rule["synonyms"]):
                return std
    for std, rule in gmap.items():
        if any(k.lower() in title.lower() for k in rule["title_keywords"]):
            return std
    return UNKNOWN_GENRE


def make_series_key(channel_id: str, title: str) -> str:
    """같은 프로그램의 회차를 묶는 키. TODO: 회차 표기("3회", "(3)") 떼기 규칙."""
    return f"{channel_id}:{title}"


def normalize_uplus(raw: dict[str, Any]) -> tuple[list[ChannelDraft], list[ProgramDraft]]:
    """U+ 원본 → 채널·방송. 끝 시각은 다음 방송 시작으로 채운다."""
    channels: list[ChannelDraft] = []
    programs: list[ProgramDraft] = []
    day_end = datetime.fromisoformat(raw["day_end"])
    for ch in raw["channels"]:
        channels.append(ChannelDraft(id=ch["id"], number=int(ch["number"]), name=ch["name"]))
        items = sorted(ch["programs"], key=lambda p: p["start"])
        starts = [datetime.fromisoformat(p["start"]) for p in items]
        ends = [*starts[1:], day_end]
        for p, start, end in zip(items, starts, ends, strict=True):
            programs.append(
                ProgramDraft(
                    channel_id=ch["id"],
                    title=p["title"],
                    start=start,
                    end=end,
                    genres=[to_standard_genre(p.get("genre"), p["title"])],
                    series_key=make_series_key(ch["id"], p["title"]),
                    source="uplus",
                )
            )
    return channels, programs


def normalize_skylife(raw: dict[str, Any]) -> list[ProgramDraft]:
    """스카이라이프 원본 → 방송. 채널 번호는 없음 (U+ 실패 시 채널 번호를 어디서 얻을지 TODO)."""
    raise NotImplementedError("스카이라이프 정리는 아직 구현 전")
