# AI 코딩 도구 규칙 (Claude Code · Codex 공통)

## 프로젝트
LG TUNE: webOS TV에 사는 시니어용 AI 친구. 최신 결정은 `docs/DECISIONS.md` — 작업 전에 읽을 것.
**지금 단계: 환경 세팅과 협업 맞추기.** 기술 설계(편성·기억·음성 세부)는 팀이 아직 논의 중이므로, 사람이 명시적으로 요청하지 않은 기능 구현·설계 결정은 하지 말 것.

## 사용자에 대해
팀원 대부분이 개발·GitHub 협업이 처음이다. 명령을 실행하기 전에 **무엇을 왜 하는지 한두 줄로 쉽게** 말하고, 끝나면 3줄로 요약한다. 전문용어는 `docs/협업_흐름.md` 의 비유(최종본/사본/결재 요청서)로 설명한다.

## 구조
- `backend/` Python 3.11+, FastAPI, uv. 실행 `pnpm dev:be`, 테스트 `cd backend && uv run pytest -q`, 린트 `uv run ruff check . && uv run ruff format .`
- `frontend/` React + Vite + TypeScript, pnpm. 실행 `pnpm dev:mock`(가짜 서버) 또는 `pnpm dev`
- `contracts/` 백엔드↔화면 계약. **원본은 `backend/app/contracts/*.py`**, `contracts/*.json` 과 `frontend/src/shared/api/*.ts` 는 `pnpm gen` 으로 생성 (손으로 고치지 말 것)
- `ml/` 호출어·응/아니 분류기 학습
- 각 폴더의 `CLAUDE.md` / `AGENTS.md` 에 폴더별 규칙이 더 있음

## Git 작업 순서 (반드시 이 순서. 쉬운 설명은 docs/협업_흐름.md)
1. 작업 시작 전: `git switch main && git pull`
2. **main 에서 직접 커밋하지 않는다.** 먼저 브랜치: `git switch -c <종류>/<영역>-<내용>` (종류: feat, fix, docs, chore, ml / 예: `feat/fe-편성표`)
3. 이미 main 에서 파일을 고쳤다면 커밋 전에 `git switch -c ...` 로 옮긴다 (고친 내용은 따라감)
4. 작은 단위로 커밋. 메시지: `feat(be): ...`, `fix(fe): ...`, `ml(yesno): ...`, `docs: ...`, `chore: ...`
5. 커밋 전 `pnpm test` 통과 확인
6. `git push -u origin <브랜치>` 후 **PR을 연다** (GitHub 웹의 Compare & pull request, 또는 `gh pr create`). 본문은 `.github/pull_request_template.md` 양식
7. AI는 PR을 직접 merge 하지 않는다. 사용자에게 PR 링크를 주고 "CI 초록불이면 본인이 Squash and merge" 라고 안내. 단 `contracts/` 를 바꾼 PR은 "상대 담당(백엔드↔프론트) 확인 후 merge" 라고 안내
8. 금지: main 에 `git push --force`, 사용자 확인 없는 `git reset --hard`, `ALLOW_MAIN_PUSH=1`, Git 훅 우회(`--no-verify`)
9. 충돌(conflict)은 임의로 해결하지 말고, 어떤 파일이 왜 충돌했는지 쉽게 설명하고 사용자에게 물어본다

## 반드시 지킬 것
1. **계약(`backend/app/contracts/`) 변경은 사람이 명시적으로 요청했을 때만.** 바꿨으면 `pnpm gen` 실행 후 생성 파일도 같이 커밋하고 PR에 "계약 변경 있음" 체크
2. 요청받은 폴더 밖은 고치지 않는다
3. 편성 엔진·기억 규칙·먼저 말걸기 규칙은 **테스트 먼저** 작성 (`backend/tests/`)
4. LLM·STT·TTS·재생은 어댑터 뒤에 둔다 (`fake` 구현 필수). `test` 프로필에서는 네트워크 호출 금지
5. API 키를 코드·로그·프롬프트·커밋에 넣지 않는다. `backend/.env` 에만, 코드에서는 `settings` 로만 읽기
6. 먼저 말걸기는 `segment` 가 `break`/`credits` 일 때만, 반드시 `buddy.nudge` → 반응 → `buddy.say` 순서
7. AI 친구는 음성으로만 부른다 (전용 버튼 없음). TV 조작은 `tv.action`, 영상통화 등 되돌리기 어려운 건 `confirm_required: true`
8. 외부 코드·모델·데이터를 가져오면 `docs/THIRD_PARTY.md` 에 라이선스와 함께 기록. 라이선스 없는 저장소 코드는 복사 금지
9. 끝나면 `pnpm test` 통과 확인. 사용자에게 무엇을/왜 바꿨는지 3줄로 요약 + 다음에 사람이 할 일(PR 확인 등)
