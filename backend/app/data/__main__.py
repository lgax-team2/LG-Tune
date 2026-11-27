"""실행 입구: cd backend && uv run python -m app.data --date 2026-12-01

매일 새벽 자동으로 돌리는 방법(작업 스케줄러 / 서버 안 타이머)은 나중에 정한다.
--fake 를 주면 네트워크 없이 가짜 출처로 돈다.
"""

import argparse
from datetime import date

from app.models.db import init_db, make_engine, make_session_factory
from app.settings import settings

from .pipeline import run
from .sources.fake import FakeSkylifeSource, FakeUplusSource
from .sources.skylife import SkylifeSource
from .sources.uplus import UplusSource


def main() -> None:
    parser = argparse.ArgumentParser(description="하루치 편성표 수집 → DB")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--fake", action="store_true", help="가짜 출처 사용 (네트워크 없음)")
    args = parser.parse_args()

    if args.fake or settings.profile == "test":
        uplus, skylife = FakeUplusSource(), FakeSkylifeSource()
    else:
        uplus, skylife = UplusSource(), SkylifeSource()

    engine = make_engine(settings.mymode_db_path)
    init_db(engine)
    with make_session_factory(engine)() as session:
        result = run(args.date, session, uplus, skylife)
    print(f"{result.day} 수집 완료 ({result.used}): {result.counts}")


if __name__ == "__main__":
    main()
