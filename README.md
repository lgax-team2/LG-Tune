# LG TUNE — webOS TV에 사는 친구

> 리모컨 없이 말로. 같이 보고, 같이 본 걸 기억해서, 방해되지 않는 순간에 먼저 꺼내는 TV 단짝.
> 최신 결정은 항상 [`docs/DECISIONS.md`](docs/DECISIONS.md) 를 먼저 보세요.

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
git clone https://github.com/CoSunny-713/LG-Tune.git
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

---

## 폴더 = 누가 무엇을
| 폴더 | 담당 | 내용 |
| --- | --- | --- |
| `contracts/` | 백엔드 + 프론트 **공동 승인** | 백엔드↔화면 약속(스키마)과 시연 시나리오 |
| `backend/` | 백엔드 | FastAPI 서버, 편성·기억·음성·Claude 연결 |
| `frontend/` | 프론트 | TV 화면(React), 자녀 설정, 대시보드 |
| `ml/` | AI 학습 | 응/아니 분류기 학습·평가 |
| `docs/` | 전원 | 결정 기록, 명세서 |

## 협업 규칙 (이것만 지키면 됨)
1. **`main` 에 직접 올리지 않는다.** `main` = 항상 돌아가는 완성본 (`pnpm install` 하면 실수 방지 훅이 자동 설치됨)
2. 작업 시작할 때 브랜치 만들기: `git switch -c feat/fe-편성표화면` (이름 앞머리: `feat/` 기능, `fix/` 버그, `ml/` 학습)
3. **자기 폴더만** 고친다. `contracts/` 는 백엔드·프론트 둘 다 동의할 때만
4. 다 되면 GitHub에서 **Pull Request** → 자동 검사 초록불이면 **본인이** 합치기(Squash and merge). `contracts/` 변경만 상대 담당 확인
5. 브랜치는 1~2일 안에 합친다. 길어지면 쪼개기
6. **API 키는 절대 코드·채팅에 붙여넣지 않는다.** `backend/.env` 에만 (Git에 안 올라감)

```
main  ●──────────●──────────●
        \        /  \        /
   feat/be-편성 ●─●   feat/fe-화면 ●─●
```

## 계약(스키마)이란?
백엔드가 화면에 보내는 메시지의 **모양 약속**. 예) AI 친구가 말할 때:
```json
{"v":1, "type":"buddy.say", "data":{"text":"8시에 가요무대 해요", "mode":"reminder", "audio_url":"/audio/s1.wav"}}
```
- 원본: `backend/app/contracts/*.py` → 자동 생성: `contracts/*.json` → 프론트 타입: `frontend/src/shared/api/*.ts`
- 전체 이벤트 목록: [`docs/개발계획서_v1.md`](docs/개발계획서_v1.md) 3.3절 + `backend/app/contracts/ws.py`
- 시연 흐름 예시: `contracts/scenarios/day1_evening.jsonl`

## AI 코딩 도구 (Claude Code / Codex)
저장소 루트의 `CLAUDE.md` / `AGENTS.md` 를 자동으로 읽습니다. 이슈 1개 = 브랜치 1개 = AI 세션 1개.
