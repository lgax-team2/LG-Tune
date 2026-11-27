"""데이터 수집 pipeline: 가짜 출처(값 전부 가상, 네트워크 없음)로 끝까지 돌아 DB에 들어가는지."""

from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.data.pipeline import run
from app.data.sources.fake import FakeSkylifeSource, FakeUplusSource
from app.models.db import Channel, Program, init_db, make_engine, make_session_factory

DAY = date(2026, 12, 1)


@pytest.fixture
def session(tmp_path):
    engine = make_engine(tmp_path / "t.db")
    init_db(engine)
    with make_session_factory(engine)() as s:
        yield s


def test_pipeline_runs_end_to_end_with_fake_sources(session, tmp_path):
    raw_dir = tmp_path / "raw"
    result = run(DAY, session, FakeUplusSource(), FakeSkylifeSource(), raw_dir=raw_dir)

    assert result.used == "uplus+skylife"
    # 채널 번호 = U+ 채널 번호
    assert session.get(Channel, "VCH1").number == 101
    # U+ 는 시작 시각만 → 끝 = 다음 방송 시작, 마지막 방송은 day_end
    progs = session.scalars(select(Program).where(Program.channel_id == "VCH1").order_by(Program.start)).all()
    assert [p.end for p in progs] == [datetime(2026, 12, 1, h) for h in (7, 8, 9)]
    # 장르는 표준 장르로 ("보도" → "뉴스")
    assert progs[0].genre == "뉴스"
    # 원본은 저장되고, 폴더에 Git 제외용 .gitignore 가 생김
    assert (raw_dir / "2026-12-01" / "uplus.json").exists()
    assert (raw_dir / ".gitignore").read_text(encoding="utf-8").strip().endswith("*")
