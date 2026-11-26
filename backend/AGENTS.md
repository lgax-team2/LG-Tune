# backend/ 규칙 (루트 AGENTS.md 규칙도 함께 적용)

| 폴더 | 담당 | 내용 |
| --- | --- | --- |
| `app/models/` | 공통 | DB 구조(`db.py`), 공통 샘플 불러오기(`sample.py`) |
| `app/contracts/` | 공통 | API 응답 모양 (Pydantic). 바꾸면 `pnpm gen` |
| `app/api/` | 영역별 파일 | `schedules.py`(B), `admin.py`(A), `tts.py`·`control.py`(C) |
| `app/data/` | A | 편성표(XMLTV)·인물·채널 번호표 → DB |
| `app/engine/` | B | 취향 추정 → 점수 → 배치(DP) → 빈 시간 |
| `app/voice/`, `app/devices/` | C | 음성 안내, 채널 바꾸기(지금은 가상) |
| `app/chat/`, `app/memory/`, `app/llm/` | 보류 | 대화 에이전트 1단계. LLM 어댑터는 fake/claude/openai |

- 설정은 `app/settings.py` + `backend/.env` (예시 `.env.example`). 비밀값은 절대 코드에
- 외부 서비스는 어댑터로 감싸고 `fake` 구현을 먼저 만든다. 테스트는 네트워크 없이 통과해야 함
- 샘플 다시 만들기 `uv run python scripts/make_sample.py`, 개발 DB에 넣기 `uv run python scripts/load_sample.py`
- PR 전 확인: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
