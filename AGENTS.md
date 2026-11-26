# AI 코딩 도구 규칙 (Claude Code · Codex · Gemini 공통 원본)

> 이 파일이 원본. `CLAUDE.md`·`GEMINI.md` 는 이 파일을 불러오기만 한다. 규칙은 여기서만 고친다.

## 프로젝트
**마이모드 (LG TUNE)**: 시니어용 TV 콘텐츠 **하루표(편성) + 묻는 말에 답하는 추천 에이전트**.
최신 결정은 `docs/DECISIONS.md`, 데이터·API 약속은 `docs/약속.md` — 작업 전에 읽을 것.
**지금 단계: 0단계(뼈대·약속·샘플) → 1단계 각자 동시에.** 약속에 없는 설계 결정은 사람에게 먼저 물어볼 것.

## 사용자에 대해
팀원 대부분이 개발·GitHub 협업이 처음이다. 명령을 실행하기 전에 **무엇을 왜 하는지 한두 줄로 쉽게** 말하고, 끝나면 3줄로 요약한다. 전문용어는 `docs/협업_흐름.md` 의 비유(최종본/사본/결재 요청서)로 설명한다.

## 구조와 담당
| 담당 | 맡는 일 | 고칠 수 있는 폴더 |
| --- | --- | --- |
| A · 데이터 | 편성표·인물·채널 번호표, DB 넣기 → 가족 화면 | `backend/app/data/`, `frontend/src/family/` |
| B · 하루표 엔진 | 취향 추정·점수·배치·빈 시간, 하루표 API | `backend/app/engine/`, `backend/app/api/schedules.py` |
| C · TV 화면·연동 | TV 화면, 가상 시계·채널 전환, 음성 | `frontend/src/tv/`, `backend/app/voice/`, `backend/app/devices/` |
| **공통** (3명 확인) | DB 구조, 약속, 서버 시작점, 규칙 | `backend/app/models/`, `backend/app/contracts/`, `backend/app/main.py`, `data/sample/`, `docs/`, `AGENTS.md` |

- 백엔드: Python 3.12+, FastAPI, SQLite + SQLAlchemy, uv. 실행 `pnpm dev:be`, 테스트 `pnpm test`
- 화면: React + Vite + TypeScript, pnpm. TV 화면은 1920×1080, 리모컨 키(방향·확인·뒤로=keyCode 461)만으로 조작. webOSTV.js 쓰지 않음
- API 모양 원본은 `backend/app/contracts/*.py`. `contracts/*.json`·`frontend/src/shared/api/*.ts` 는 `pnpm gen` 으로 생성 (손으로 고치지 말 것)
- 보류 기능(지우지 않음): `backend/app/chat`·`memory`·`llm` = 대화 에이전트 1단계. 나중에 "묻는 말에 답하기"에 재사용

## Git 작업 순서 (쉬운 설명은 docs/협업_흐름.md)
1. 작업 시작 전: `git switch main && git pull`
2. **할 일은 GitHub 이슈로**. 이슈 1개 = 담당 1명
3. **main 에서 직접 커밋하지 않는다.** 브랜치 이름 `영역/내용` (영역: `data`, `engine`, `tv`, `voice`, `family`, `common` / 예: `engine/scoring`)
4. 작은 단위로 커밋. 메시지: `feat: ...`, `fix: ...`, `docs: ...`, `chore: ...`
5. 커밋 전 `pnpm test` 통과 확인
6. `git push -u origin <브랜치>` 후 **PR을 연다**. 본문에 `Closes #이슈번호`. PR 크기는 하루~이틀치
7. merge:
   - **자기 폴더만 고친 PR** → CI 초록불이면 **본인이** Squash and merge (Checks 가 0 이면 Update branch 먼저)
   - **공통 폴더를 고친 PR** → 3명 모두 확인 후 merge. API 모양을 **추가만** 했으면 단톡 알림으로 갈음
   - AI는 merge 버튼을 직접 누르지 않는다. PR 링크를 주고 위 기준을 안내
8. 금지: main 에 `git push --force`, 사용자 확인 없는 `git reset --hard`, `ALLOW_MAIN_PUSH=1`, Git 훅 우회(`--no-verify`)
9. 충돌(conflict)은 임의로 해결하지 말고, 어떤 파일이 왜 충돌했는지 쉽게 설명하고 사용자에게 물어본다

## 반드시 지킬 것
1. **자기 담당 폴더만** 고친다. 공통 폴더는 필요하면 따로 PR
2. API 모양(`contracts/`)이나 DB 구조(`models/`)를 바꾸면 `docs/약속.md` 도 같이 고치고, `pnpm gen` 결과도 같이 커밋
3. 하루표 엔진 규칙은 **테스트 먼저** 작성 (`backend/tests/`). 샘플(`data/sample/`)로 테스트
4. LLM·TTS·장치 제어는 어댑터 뒤에 둔다 (`fake` 구현 필수). `test` 프로필에서는 네트워크 호출 금지
5. API 키는 `backend/.env` 에만, 코드에서는 `settings` 로만 읽기. 저장소·메신저에 올리지 않기
6. 외부 코드·모델·데이터(편성표, TMDB 등)를 가져오면 `docs/THIRD_PARTY.md` 에 라이선스와 함께 기록. 방송 영상·로고는 쓰지 않음
7. 끝나면 `pnpm test` 통과 확인. 사용자에게 무엇을/왜 바꿨는지 3줄로 요약 + 다음에 사람이 할 일(PR 확인 등)
