# backend/ 규칙 (백엔드 담당용 · 루트 CLAUDE.md 규칙도 함께 적용)

- 이 폴더 안만 고친다 (+ 계약 변경 시 `pnpm gen` 이 만드는 생성 파일). 브랜치 `feat/be-...`, 커밋 `feat(be): ...`
- 계약 원본: `app/contracts/ws.py`, `app/contracts/rest.py`. 사람이 요청했을 때만 수정 → `pnpm gen` → 생성 파일 같이 커밋 → PR에 "계약 변경 있음" + 프론트 담당 리뷰 요청
- 설정은 `app/settings.py` + `backend/.env` (예시 `.env.example`). 비밀값은 절대 코드에
- 외부 서비스(LLM·STT·TTS·JEV 등)는 어댑터로 감싸고 `fake` 구현을 먼저 만든다. 테스트는 네트워크 없이 통과해야 함
- PR 전 확인: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
- 기술 설계(편성 점수, 기억 구조, 음성 파이프라인 세부)는 팀 논의 중 → 사람이 정해준 범위만 구현
