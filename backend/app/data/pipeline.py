"""하루치 편성표 수집 전체 순서.

받기 → 원본 저장 → 정리 → 짝짓기 → 보강 → DB 넣기

실패 시:
- U+ 실패 → 스카이라이프만으로 (TODO: normalize_skylife)
- 둘 다 실패 → 전날 저장본으로 (TODO: raw_store.latest_before)
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from . import load as loader
from . import merge as merger
from .enrich import cast
from .normalize import normalize_uplus
from .raw_store import RAW_DIR, save_raw
from .sources import ScheduleSource, SourceError

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    day: date
    used: str  # "uplus+skylife" | "uplus" | "skylife" | "previous"
    counts: dict[str, int] = field(default_factory=dict)


def run(
    day: date,
    session: Session,
    uplus: ScheduleSource,
    skylife: ScheduleSource,
    raw_dir: Path = RAW_DIR,
) -> RunResult:
    """그날 편성표를 받아 DB에 넣는다."""
    u_raw = _try_fetch(uplus, day, raw_dir)
    s_raw = _try_fetch(skylife, day, raw_dir)

    if u_raw is None:
        if s_raw is None:
            raise NotImplementedError("둘 다 실패 → 전날 저장본 대체는 아직 구현 전")
        raise NotImplementedError("U+ 실패 → 스카이라이프만 쓰기는 아직 구현 전")

    channels, programs = normalize_uplus(u_raw)
    used = "uplus"
    if s_raw is not None:
        programs = merger.merge(programs, [])  # TODO: normalize_skylife(s_raw) 결과로 짝짓기
        used = "uplus+skylife"
    programs = cast.add_cast(programs)
    counts = loader.load(session, channels, programs)
    return RunResult(day=day, used=used, counts=counts)


def _try_fetch(source: ScheduleSource, day: date, raw_dir: Path) -> dict | None:
    """받아서 원본을 저장한다. 실패하면 기록만 남기고 None."""
    try:
        raw = source.fetch(day)
    except (SourceError, NotImplementedError) as e:
        log.warning("%s 수집 실패: %s", source.name, e)
        return None
    save_raw(day, source.name, raw, raw_dir)
    return raw
