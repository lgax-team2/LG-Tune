# 마이모드 (LG TUNE) — 시니어 TV 하루표 + 추천 에이전트

> TV를 켜면 내 취향에 맞춘 하루표가 있고, 궁금한 걸 물어보면 답해 주는 TV.
> 최신 결정은 [`docs/DECISIONS.md`](docs/DECISIONS.md), 데이터·API 약속은 [`docs/약속.md`](docs/약속.md), 누가 어느 폴더인지는 [`AGENTS.md`](AGENTS.md).

---

## 역할별 시작하기
| 누구 | 먼저 읽을 문서 |
| --- | --- |
| **GitHub이 처음이면** | [`docs/협업_흐름.md`](docs/협업_흐름.md) — 브랜치·PR·Merge 비유로 이해하기 |
| 전원 (첫날) | [`docs/onboarding/00_공통_첫날.md`](docs/onboarding/00_공통_첫날.md) — 설치 + 첫 PR 연습 |
| 프론트 | [`docs/onboarding/01_프론트.md`](docs/onboarding/01_프론트.md) |
| AI 학습 | [`docs/onboarding/02_AI.md`](docs/onboarding/02_AI.md) |
| 회의 진행 | [`docs/onboarding/03_킥오프_회의.md`](docs/onboarding/03_킥오프_회의.md) |
| 꼬였을 때 | [`docs/onboarding/04_꼬였을때.md`](docs/onboarding/04_꼬였을때.md) — 안전장치와 응급처치 |

## 처음 오신 분: 10분 시작 가이드

### 1. 설치 (한 번만)
| 도구 | 설치 |
| --- | --- |
| Git | https://git-scm.com |
| Node 20+ / pnpm | Node 설치 후 터미널에서 `npm i -g pnpm` |
| Python 도구 uv (백엔드·ML만) | PowerShell: `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| VS Code | 권장 |

### 2. 내려받기
```bash
git clone https://github.com/lgax-team2/LG-Tune.git
cd LG-Tune
pnpm install            # 루트 도구
pnpm setup              # 백엔드 + 프론트 의존성 설치
```

### 3. 실행
| 명령 | 언제 |
| --- | --- |
| `pnpm dev:mock` | **프론트 담당**: 백엔드 없이 가짜 서버 + 화면 (http://localhost:5173) |
| `pnpm dev` | 백엔드 + 화면 같이 |
| `pnpm gen` | 계약(스키마)이 바뀌었을 때 → 프론트 타입 다시 생성 |
| `pnpm test` | 올리기 전에 검사 |
| `pnpm sample` | 공통 샘플을 개발 DB(`backend/data/mymode.db`)에 새로 넣기 |

---

## 폴더 = 누가 무엇을
| 폴더 | 담당 | 내용 |
| --- | --- | --- |
| `backend/app/data/`, `frontend/src/family/` | A · 데이터 | 편성표·인물·채널 번호표 → DB, 가족 화면 |
| `backend/app/engine/`, `backend/app/api/schedules.py` | B · 하루표 엔진 | 취향 추정·점수·배치·빈 시간, 하루표 API |
| `frontend/src/tv/`, `frontend/src/remote/`, `backend/app/voice/`, `backend/app/devices/` | C · TV 화면·연동 | TV 화면, 폰 리모컨, 가상 시계·채널 전환, 음성 |
| `backend/app/models/`, `backend/app/contracts/`, `main.py`, `data/sample/`, `docs/` | **공통 (3명 확인)** | DB 구조, API 약속, 공통 샘플, 결정 기록 |
| `backend/app/chat`·`memory`·`llm`, `ml/` | 보류 | 이전 범위(대화·음성) 코드. 나중에 재사용 |

## 협업 규칙 (이것만 지키면 됨)
1. **`main` 에 직접 올리지 않는다.** `main` = 항상 돌아가는 완성본 (`pnpm install` 하면 실수 방지 훅이 자동 설치됨)
2. 할 일은 GitHub 이슈로 올리고, 브랜치 만들기: `git switch -c engine/scoring` (`영역/내용`)
3. **자기 폴더만** 고친다. 공통 폴더(`models/`, `contracts/`, `main.py`, `data/sample/`, `docs/`)는 3명 동의할 때만
4. 다 되면 GitHub에서 **Pull Request** → 자동 검사 초록불이면 **본인이** 합치기(Squash and merge). 공통 폴더 변경만 3명 확인
5. 브랜치는 1~2일 안에 합친다. 길어지면 쪼개기
6. **API 키는 절대 코드·채팅에 붙여넣지 않는다.** `backend/.env` 에만 (Git에 안 올라감)

```
main  ●──────────●──────────●
        \        /  \        /
   engine/scoring ●─●   tv/popup ●─●
```

## 계약(스키마)이란?
백엔드가 화면에 보내는 데이터의 **모양 약속**. 예) 하루표의 한 칸 (`GET /api/schedules/s1`):
```json
{"program_id":"KBS1-20261201-2030", "channel_number":9, "title":"일일드라마 햇살 가득", "start":"2026-12-01T20:30:00", "reason":"매일 보시는 드라마 새 회차예요", "kind":"pick"}
```
- 원본: `backend/app/contracts/*.py` → 자동 생성: `contracts/*.json` → 프론트 타입: `frontend/src/shared/api/*.ts`
- 전체 약속: [`docs/약속.md`](docs/약속.md) · 공통 샘플: `data/sample/`

## AI 코딩 도구 (Claude Code / Codex / Gemini)
규칙 원본은 `AGENTS.md` 하나. `CLAUDE.md`·`GEMINI.md` 는 그걸 불러오기만 합니다. 이슈 1개 = 브랜치 1개 = AI 세션 1개.
