"""DB 구조 (공통 약속 · SQLite + SQLAlchemy).

표 5개:
| 표 | 한 줄 = | 누가 채우나 |
| channels | 채널 하나 (번호·이름) | A |
| programs | 편성표의 방송 한 편 | A |
| seniors | 가상 어르신 한 명 (첫날 정보 포함) | A(가족 화면) |
| watch_logs | 시청 기록 한 건 | C(TV 화면) / 샘플 |
| plan_items | 엔진이 만든 하루표의 한 칸 | B |

바꾸면 docs/약속.md 도 같이 고치고 3명 모두 확인.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Literal

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

Feedback = Literal["none", "next", "help"]  # next = "다음에" (−0.3), help = "됐다/그만" (−0.5)
PrefSource = Literal["child", "self", "age_default"]  # 첫날 정보 출처: 자녀 입력 > 본인 선택 > 나이대 기본값


class Base(DeclarativeBase):
    type_annotation_map: ClassVar = {dict[str, Any]: JSON, list[str]: JSON}


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # 예: "KBS1"
    number: Mapped[int] = mapped_column(Integer)  # 리모컨 채널 번호 (통신사마다 다름 → A가 표로 관리)
    name: Mapped[str] = mapped_column(String)


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id"))
    title: Mapped[str] = mapped_column(String)
    series_key: Mapped[str] = mapped_column(String, index=True)  # 같은 프로그램의 회차를 묶는 키
    genre: Mapped[str] = mapped_column(String)
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime] = mapped_column(DateTime)
    cast: Mapped[list[str]] = mapped_column(default=list)  # 출연자 이름
    is_new: Mapped[bool] = mapped_column(default=False)  # 새 회차 (재방송 아님)
    is_live: Mapped[bool] = mapped_column(default=False)  # 생방송


class Senior(Base):
    __tablename__ = "seniors"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    age: Mapped[int] = mapped_column(Integer)
    wake_time: Mapped[str] = mapped_column(String, default="06:00")  # HH:MM
    sleep_time: Mapped[str] = mapped_column(String, default="22:00")
    pref_source: Mapped[str] = mapped_column(String, default="age_default")  # PrefSource
    # 첫날 정보: {"series": [...], "cast": [...], "genres": [...]}
    seed_prefs: Mapped[dict[str, Any]] = mapped_column(default=dict)
    family_picks: Mapped[list[str]] = mapped_column(default=list)  # 가족이 추천한 series_key


class WatchLog(Base):
    __tablename__ = "watch_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    senior_id: Mapped[str] = mapped_column(ForeignKey("seniors.id"), index=True)
    channel_id: Mapped[str] = mapped_column(String)
    series_key: Mapped[str] = mapped_column(String)
    genre: Mapped[str] = mapped_column(String)
    cast: Mapped[list[str]] = mapped_column(default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    watched_min: Mapped[float] = mapped_column(Float)  # 5분 미만은 취향 계산에서 무시
    feedback: Mapped[str] = mapped_column(String, default="none")  # Feedback


class PlanItem(Base):
    __tablename__ = "plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    senior_id: Mapped[str] = mapped_column(ForeignKey("seniors.id"), index=True)
    date: Mapped[str] = mapped_column(String, index=True)  # YYYY-MM-DD
    program_id: Mapped[str] = mapped_column(ForeignKey("programs.id"))
    score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String)  # 화면에 보여 줄 고른 이유
    kind: Mapped[str] = mapped_column(String, default="pick")  # pick(점수로 고름) | fill(빈 시간 채움)


def make_engine(db_path: str | Path) -> Engine:
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}")


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(engine, expire_on_commit=False)
