# 마이모드 (LG TUNE) — 시니어 TV 하루표 + 추천 에이전트

> TV를 켜면 내 취향에 맞춘 하루표가 있고, 궁금한 걸 물어보면 답해 주는 TV.
> 문서는 3개뿐: [`docs/기획.md`](docs/기획.md) (무엇을·언제) · [`docs/명세.md`](docs/명세.md) (DB·API·엔진 규칙) · [`docs/협업.md`](docs/협업.md) (Git·팀·응급처치). 누가 어느 폴더인지는 [`AGENTS.md`](AGENTS.md).

---

## 문서 안내
| 언제 | 문서 |
| --- | --- |
| 무엇을 만드는지·일정 | [`docs/기획.md`](docs/기획.md) |
| DB·API 모양, 하루표 엔진 규칙 | [`docs/명세.md`](docs/명세.md) |
| GitHub이 처음이거나 꼬였을 때 | [`docs/협업.md`](docs/협업.md) |
| AI 코딩 도구 규칙·담당 폴더 | [`AGENTS.md`](AGENTS.md) |

## 처음 오신 분: 10분 시작 가이드

### 1. 설치 (한 번만)
| 도구 | 설치 |
| --- | --- |
| Git | https://git-scm.com |
| Node 22.12+ / pnpm | Node 설치 후 터미널에서 `npm i -g pnpm` |
| Python 도구 uv (백엔드) | PowerShell: `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
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
| `pnpm dev` | 백엔드 + 화면 같이 (http://localhost:5173) |
| `pnpm dev:mock` | 백엔드 없이 가짜 서버 + 화면 (옛 시나리오 재생, 하루표 기준 아님) |
| `pnpm gen` | 계약(스키마)이 바뀌었을 때 → 프론트 타입 다시 생성 |
| `pnpm test` | 올리기 전에 검사 |
| `pnpm sample` | 공통 샘플을 개발 DB(`backend/data/mymode.db`)에 새로 넣기 |

### 4. 첫날 체크리스트 (전원 · 약 30분)
| # | 할 일 | 확인 |
| --- | --- | --- |
| 1 | GitHub 초대 수락 | 저장소가 보임 |
| 2 | 위 1~3 설치·실행 | `pnpm dev` 로 화면이 뜸 |
| 3 | **첫 PR 연습** (아래) | PR이 main에 합쳐짐 |
| 4 | `docs/기획.md` → `docs/명세.md` 읽기 | |

```bash
git switch -c common/team-내이름          # 1. 내 브랜치 만들기
# 2. docs/협업.md 의 "팀" 표에 내 줄 추가하고 저장
git add docs/협업.md
git commit -m "chore: 팀원 추가 (내이름)"
git push -u origin common/team-내이름     # 3. GitHub에 올리기
```
4. GitHub 저장소 페이지의 **Compare & pull request** → 생성 → 자동 검사 초록불이면 **Squash and merge**
5. 내 컴퓨터 최신화: `git switch main && git pull`

> 막히면 에러 메시지 전체를 단톡이나 Claude/Codex에 붙여넣기. **API 키·비밀번호는 절대 붙여넣지 않기.**

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
- 전체 명세: [`docs/명세.md`](docs/명세.md) · 공통 샘플: `data/sample/`

## AI 코딩 도구 (Claude Code / Codex / Gemini)
규칙 원본은 `AGENTS.md` 하나 (폴더별 규칙도 그 안에). `CLAUDE.md`·`GEMINI.md` 는 그걸 불러오기만 합니다. 이슈 1개 = 브랜치 1개 = AI 세션 1개.

## PR 자동 리뷰 (CodeRabbit)
PR을 열면 CodeRabbit이 `AGENTS.md`·`docs/기획.md`·`docs/명세.md` 기준으로 리뷰를 달아 줍니다. 설정은 `.coderabbit.yaml` (공통 파일).

| 무엇이 달리나 | 내용 |
| --- | --- |
| **Walkthrough** (첫 댓글) | 전체 요약, 바뀐 파일별 요약, **구조 그림**(어떤 코드가 어떤 순서로 불리는지), 리뷰 난이도 |
| 코드 리뷰 댓글 | 핵심 2~3개만, "왜 + 예시 코드"로. 담당 폴더 밖 수정·API 키·명세 불일치도 짚어 줌 |

| PR 댓글로 쓰는 명령 | 하는 일 |
| --- | --- |
| `@coderabbitai review` | 최신 변경분 리뷰 (**저장소 스타가 10개 미만이면 자동으로 안 돌아서 이걸로 시작**) |
| `@coderabbitai full review` | PR 전체를 처음부터 다시 리뷰 |
| `@coderabbitai 질문` | 리뷰 댓글에 답글로 물어보기 (예: "이거 왜 문제야?") |

- 초안(Draft) PR은 리뷰하지 않음. 준비되면 **Ready for review** 로 바꾸기
- AI 리뷰는 참고용. 틀릴 수 있으니 그대로 따르지 말고 판단하고, 합치기 기준(CI 초록불·공통 폴더 3명 확인)은 그대로
- 무료(오픈소스) 플랜이라 리뷰 횟수에 시간당 한도가 있음. 같은 PR에 명령을 연달아 쓰지 않기
