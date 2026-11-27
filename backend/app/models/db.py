"""DB 구조 (공통 약속 · SQLite + SQLAlchemy).

표 7개:
| 표 | 한 줄 = | 누가 채우나 |
| channels | 채널 하나 (번호·이름) | A |
| programs | 편성표의 방송 한 편 | A |
| lg_contents | 빈 시간에 끼울 LG채널·VOD 콘텐츠 | A |
| seniors | 가상 어르신 한 명 (첫날 정보 포함) | A(가족 화면) |
| watch_logs | 시청 기록 한 건 | C(TV 화면) / 샘플 |
| user_rules | 음성 명령으로 생긴 규칙 (빼기·챙기기·오늘만·쉬기) | B(음성 명령 API) |
| plan_items | 엔진이 만든 하루표의 한 칸 | B |

바꾸면 docs/명세.md 도 같이 고치고 3명 모두 확인.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Literal

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

Feedback = Literal["none", "next", "help"]  # 기록용. 엔진은 점수로 깎지 않음 (확실한 거절은 user_rules)
HowStarted = Literal[
    "chosen", "continued", "plan"
]  # 직접 고름(말·리모컨) / 앞 방송에서 이어짐 / 하루표 추천으로
RuleKind = Literal[
    "exclude", "pin", "skip_today", "rest_day", "unpause"
]  # 앞으로 빼기 / 항상 챙기기 / 오늘만 넘기기 / 오늘은 그만 / 쉬어가기 되돌리기(그날까지의 반복 거절은 잊음)
EndReason = Literal["completed", "skipped", "help_cancel", "channel_change", "power_off"]  # 시청이 끝난 이유
CastRole = Literal["host", "lead", "regular", "guest"]  # 진행자·주연 / 고정 출연 / 손님
PrefSource = Literal[
    "child", "self", "none"
]  # 첫날 관심사 출처: 자녀가 설치 때 고름 > 본인이 고름 > 없음 (기본 장르는 두지 않음)


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
    genre: Mapped[str] = mapped_column(String)  # 대표 장르 1개
    genres: Mapped[list[str]] = mapped_column(default=list)  # 장르 전부 (외부 편성표). 비면 [genre] 로 봄
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime] = mapped_column(DateTime)
    cast: Mapped[list[str]] = mapped_column(default=list)  # 출연자 이름
    cast_roles: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {이름: CastRole}, 없으면 역할 무게 1.0
    episode: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # 회차 (같은 회차는 하루 1번). 모르면 None
    is_new: Mapped[bool] = mapped_column(default=False)  # 새 회차 (재방송 아님)
    is_live: Mapped[bool] = mapped_column(default=False)  # 생방송


class Senior(Base):
    __tablename__ = "seniors"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    age: Mapped[int] = mapped_column(Integer)
    wake_time: Mapped[str] = mapped_column(String, default="06:00")  # HH:MM
    sleep_time: Mapped[str] = mapped_column(String, default="22:00")
    pref_source: Mapped[str] = mapped_column(String, default="none")  # PrefSource
    # 첫날 정보: {"series": [...], "cast": [...], "genres": [...]}
    seed_prefs: Mapped[dict[str, Any]] = mapped_column(default=dict)
    family_picks: Mapped[list[str]] = mapped_column(default=list)  # 가족이 추천한 series_key
    fixed_breaks: Mapped[list[str]] = mapped_column(
        default=list
    )  # 매일 비우는 시간 ["12:00-12:30"] (식사·약, 가족 입력)


class WatchLog(Base):
    __tablename__ = "watch_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    senior_id: Mapped[str] = mapped_column(ForeignKey("seniors.id"), index=True)
    channel_id: Mapped[str] = mapped_column(String)
    series_key: Mapped[str] = mapped_column(String)
    genre: Mapped[str] = mapped_column(String)  # 대표 장르 1개
    genres: Mapped[list[str]] = mapped_column(default=list)  # 장르 전부. 비면 [genre] 로 봄
    cast: Mapped[list[str]] = mapped_column(default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    watched_min: Mapped[float] = mapped_column(Float)  # 5분 미만은 취향 계산에서 무시
    feedback: Mapped[str] = mapped_column(String, default="none")  # Feedback
    how_started: Mapped[str] = mapped_column(String, default="chosen")  # HowStarted
    cancelled: Mapped[bool] = mapped_column(default=False)  # "방금 거 취소" → 학습에서 제외
    end_reason: Mapped[str | None] = mapped_column(
        String, nullable=True, default="completed"
    )  # EndReason (없으면 끝까지 봄)


class LgContent(Base):
    """빈 시간에 끼울 LG채널(무료 채널)·VOD 콘텐츠. 시간에 맞춰 언제든 틀 수 있다고 가정."""

    __tablename__ = "lg_contents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    genre: Mapped[str] = mapped_column(String)
    cast: Mapped[list[str]] = mapped_column(default=list)
    duration_min: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String, default="LG채널")  # LG채널 | LG VOD


class UserRule(Base):
    """음성 명령으로 생긴 규칙. 점수가 아니라 규칙이라 반드시 지켜진다."""

    __tablename__ = "user_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    senior_id: Mapped[str] = mapped_column(ForeignKey("seniors.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # RuleKind
    target_type: Mapped[str] = mapped_column(String, default="series")  # series | genre | none
    target: Mapped[str] = mapped_column(String, default="")  # series_key 또는 장르
    date: Mapped[str | None] = mapped_column(String, nullable=True)  # skip_today·rest_day 는 그날만
    from_time: Mapped[str | None] = mapped_column(String, nullable=True)  # rest_day: 이 시각(HH:MM)부터 쉬기
    active: Mapped[bool] = mapped_column(default=True)  # "방금 거 취소" → False
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class PlanItem(Base):
    __tablename__ = "plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    senior_id: Mapped[str] = mapped_column(ForeignKey("seniors.id"), index=True)
    date: Mapped[str] = mapped_column(String, index=True)  # YYYY-MM-DD
    program_id: Mapped[str] = mapped_column(String)  # programs.id 또는 lg_contents.id
    score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String)  # 화면에 보여 줄 고른 이유
    kind: Mapped[str] = mapped_column(String, default="pick")  # pick | fill(채널 유지) | lg(LG 콘텐츠)


def make_engine(db_path: str | Path) -> Engine:
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}")


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(engine, expire_on_commit=False)
