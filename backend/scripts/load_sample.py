"""공통 샘플을 개발용 DB(backend/data/mymode.db)에 새로 넣는다. 기존 내용은 지움.

실행: (backend 폴더에서) uv run python scripts/load_sample.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.db import Base, init_db, make_engine, make_session_factory
from app.models.sample import load_sample
from app.settings import settings

engine = make_engine(settings.mymode_db_path)
Base.metadata.drop_all(engine)
init_db(engine)
with make_session_factory(engine)() as session:
    counts = load_sample(session)
print(f"{settings.mymode_db_path} 에 샘플을 넣었어요: {counts}")
