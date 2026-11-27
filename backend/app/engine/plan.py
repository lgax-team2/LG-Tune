"""하루표 자료형: 한 칸(Entry)과 하루표 전체(Plan).

Plan 은 칸 목록과 함께 "왜 이렇게 짰는지" 기록(빠진 방송 이유, 못 지킨 목표)을 들고 다닌다.
확인 화면과 기준표 판정(quality.py)은 이 기록을 그대로 읽는다 (따로 다시 계산하지 않음).
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .scoring import Scored

# 칸의 역할
NORMAL = "normal"  # 점수로 고른 방송
PIN = "pin"  # "매일 챙겨 줘"
REPRESENTATIVE = "representative"  # 오늘의 대표 방송 (기준표 S1)
NOVELTY = "novelty"  # 새로 추천 (기준표 S5)
BACKGROUND = "background"  # 배경 편성: TV 를 켜 두는 시각의 빈 시간을 앞 채널·취향 LG 로 이어 줌


@dataclass
class Entry:
    program_id: str
    channel_id: str
    title: str
    start: datetime
    end: datetime
    score: float
    kind: str  # pick | fill | lg  (API 의 ScheduleItem.kind)
    scored: Scored | None = None
    source: Any = field(default=None, repr=False)  # Program 또는 LgContent
    role: str = NORMAL
    reason: str = ""  # 화면에 보여 줄 이유 (reason.py 가 채움)
    basis: str = ""  # 이유의 근거 코드 (예: "cast:송미란") — 기준표 M5 검사용

    @property
    def minutes(self) -> int:
        return round((self.end - self.start).total_seconds() / 60)

    @property
    def pinned(self) -> bool:
        return self.role == PIN


@dataclass
class Plan:
    entries: list[Entry]
    floor: float  # 기준점
    budget_min: float  # 하루 pick 시간 상한
    hours: set[int]  # 시청 시간대 (TV 켜짐 '중간' 이상인 시각)
    knows_taste: bool  # 관심사·기록으로 취향을 아는가
    favorite_genre: str | None = None
    scores: dict[str, float] = field(default_factory=dict)  # 오늘 방송 program_id → 점수
    dropped: dict[str, str] = field(default_factory=dict)  # 하루표에 없는 방송 program_id → 빠진 이유
    notes: dict[str, str] = field(default_factory=dict)  # 기준표 목표 코드(S1…) → 못 지킨 이유·해당 없음 설명
    day: date | None = None
    rests: list[tuple[datetime, datetime]] = field(default_factory=list)  # 쉬는 시간 (켜짐 '낮음' 빈 시간)

    def picks(self) -> list[Entry]:
        return [e for e in self.entries if e.kind == "pick"]

    def with_role(self, role: str) -> list[Entry]:
        return [e for e in self.entries if e.role == role]
