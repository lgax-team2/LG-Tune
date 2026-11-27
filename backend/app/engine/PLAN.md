# B 담당 작업 계획 (하루표 엔진 · 음성 명령 · 질문 답하기)

> 목표: 하루표 엔진·API 를 **시연 가능한 상태**로 끝내고, 처음 온 개발자도 이어받을 수 있게 정리.
> 진행: 작업 1개씩 "다음" → 테스트 먼저(TDD) → Codex 리뷰 → 반영 → `pnpm test` → 커밋·push(engine/rules) → 여기 체크 + 진행 기록.
> 확인 화면: `pnpm dev:be` 후 http://localhost:8000/api/schedules/s1/view (s2·s3 는 주소의 s1 만 바꿈)
> 현재 PR: #3 (engine/rules → main, draft)

## 진행 규칙
Codex 활용 (항상, 코드는 고치지 말고 의견만 받기)
1. 커밋 직전: `codex exec` 로 diff 리뷰 (AGENTS.md 기준, 심각한 것 3개 이내)
2. 사람에게 결정을 물어보기 전: `codex exec` 로 선택지 비교·추천을 먼저 받고, 보고에 "Codex 의견" 칸을 따로 둠
3. 같은 테스트가 2번 실패하면: `codex exec` 로 원인 의견 받기
4. 중간 합치기 전(②·⑥·⑨): `codex exec` 로 이번 구간 전체 diff 리뷰
- Codex 의견은 맞는지 먼저 판단하고(receiving-code-review), 내 의견과 다르면 둘 다 보여 줌
- 3줄 보고에 "Codex: 한 줄 요약"을 항상 포함

## 정한 것 (2026-11-26 승인)
- 기본값: 장르 여러 개는 각각 같은 무게 / 출연자 없으면 그 항목 빼고 ÷0.75 / 확인 대기는 서버 메모리 / 알림은 `/ws/events` / fake LLM 답은 문장 틀 / 시계 기본 12-01 06:00·1배
- `make_sample.py` 수정은 ②에 한해 허용, `tests/snapshots/` 허용, `commands_draft.py` 없이 약속 4절 기준, 가상 시계는 B 가 `api/clock.py` 로

## 지킬 것 (모든 작업 공통)
- 고칠 수 있음: `backend/app/engine/*`, `backend/app/api/{schedules,commands,events,clock}.py`, `backend/app/api/views/*`, `backend/tests/test_engine*.py`, `backend/tests/test_api_*.py`
- 공통 파일은 작업에 적힌 것만 (config 숫자, `docs/명세.md`, `app/models/db.py`, `data/sample/*`, `contracts/rest.py`·`ws.py` 추가만, `pnpm gen` 결과). 고치기 전 `gh pr list` 로 같은 파일 고치는 PR 확인 → 3줄 보고에 "공통 변경 있음, 단톡 알림 필요"
- `main.py` 는 안 고침 → "main.py 에 넣을 줄"로 보고
- LLM 은 `app/llm` 의 `make_llm(settings)` 만 사용 (기본 fake, test 프로필은 네트워크 없음)
- 커밋 전: `pnpm test` + `cd backend && uv run ruff check . && uv run ruff format --check .`
- 새 코드는 처음부터 ⑧ 기준: 파일 맨 위 "이 파일이 하는 일" 2~3줄, 함수는 한 가지 일, 이름만 봐도 역할이 보이게

---

## 작업 목록

- [x] **① 엔진 규칙 2개 변경** (취침 전 "시작"이면 허용 / 기상~첫 방송 빈 시간 채우기)
  - 고칠 파일: `engine/planner.py`, `engine/config.py`(필요 시 숫자), `api/schedules.py`(확인 화면의 "빠진 이유" 판정도 같은 규칙으로 — 엔진 함수를 같이 쓰게 해서 중복 제거), `docs/명세.md` 5·6절("기상~취침 안" 문구), `tests/test_engine.py`
  - 규칙: 후보 = `기상 ≤ 시작 < 취침` (끝나는 시간 무관). 기상~첫 칸 사이 빈 시간: 20분 미만 비움(앞 채널이 없으니 fill 안 함), 20분 이상 LG채널·VOD 중 점수 최고 1개
  - 테스트(먼저): `test_show_starting_before_sleep_is_allowed_even_if_it_ends_after`, `test_show_starting_at_or_after_sleep_is_not_allowed`, `test_morning_gap_of_20min_or_more_gets_lg_content_at_wake_time`, `test_morning_gap_under_20min_stays_empty`
  - 끝 기준: s1 에 "별의 노래 21:00" 들어감, s1·s3 아침 첫 칸이 기상 후 20분 안에 시작
  - 확인 화면에서 볼 것: s1 표 맨 아래 21:00 별의 노래, s1·s3 표 맨 위 칸 시작 시각 = 기상 시각 근처(LG 콘텐츠)

- [x] **② 외부 편성표 호환** (장르 여러 개, 출연자 없는 방송, 빠진 칸)
  - 고칠 파일: `models/db.py`(programs·watch_logs 에 `genres: list[str]` 추가, 기본 `[]`. 기존 `genre` = 대표 장르로 유지), `engine/preference.py`, `engine/scoring.py`, `engine/rules.py`, `backend/scripts/make_sample.py`(②에 한해 허용, 공통) → 다시 만든 `data/sample/programs.json`·`watch_logs.json`(일부 방송에 장르 2개), `data/sample/genre_map.json`(새 파일), `docs/명세.md` 2·6절, `tests/test_engine.py`
  - 규칙:
    - 방송의 장르 목록 = `genres` 가 비어 있으면 `[genre]`
    - 장르 점수 = 장르 목록 중 **가장 좋아하는 것** 하나
    - 취향 추정: 시청 기록 한 건이 장르 목록의 **각 장르에 같은 무게**로 더해짐 (나눠 갖지 않음)
    - 출연자 정보가 없는 방송(빈 목록): 출연자 항목을 빼고 나머지 가중치 합(0.75)으로 나눠 0~1 로 맞춤. LG 콘텐츠도 같음
    - "안 볼래"로 뺀 장르는 장르 목록에 **하나라도** 있으면 막음
    - (11/26 결정 D) 배치 무게 = **(점수 − 기준점)** × min(길이,60). 출연자 보정으로 기준점을 겨우 넘은 방송 여러 개가 최애를 밀어내던 문제 해결 (A·B·C·D 비교, Codex 도 D 추천)
    - 테스트 추가: `test_several_shows_just_above_floor_cannot_push_out_a_favorite`, `test_plan_weighs_by_score_above_floor`, `test_show_scoring_exactly_at_floor_is_still_placed_when_free`
  - 호환 테스트(먼저): `test_empty_cast_is_left_out_and_other_weights_rescaled`, `test_unknown_genre_scores_zero_without_error`, `test_missing_is_new_is_live_defaults_to_false`, `test_show_crossing_midnight_is_handled`, `test_series_key_equal_to_title_works`, `test_genre_score_uses_best_liked_of_many`, `test_profile_counts_every_genre_of_a_log`, `test_excluded_genre_blocks_show_with_that_genre_among_many`
  - `genre_map.json` 초안: 표준 장르 12개 안팎 → 동의어 + 제목 키워드. **실제 적용(편성표를 넣을 때 장르 이름 바꾸기)은 A 담당** — 맨 아래 목록에 메모
  - 끝 기준: s1 취향 요약에 장르 여러 개, 하루표 점수가 크게 안 뒤바뀜 (바뀌면 이유 보고 — 예상: 출연자 없는 뉴스·교양 점수가 ÷0.75 로 오름)
  - 확인 화면에서 볼 것: s1 "취향 요약 > 장르"에 3개, 하루표 칸·점수가 ①끝과 비슷한지
  - ⏸ 끝나면 **중간 합치기** ("지금 합칠 때")

- [ ] **③ 음성 명령 API** (`POST /api/commands`, 약속 4절) + 확인 화면에 말하기 칸
  - 고칠 파일: `api/commands.py`(새로: 요청 받기·응답), `engine/commands.py`(새로: 말 해석 + 규칙 저장/취소), `contracts/rest.py`(`CommandRequest`·`CommandResponse` 추가만) → `pnpm gen`, `docs/명세.md` 4·5절, `api/views/schedule_view.html`(말하기 칸), `tests/test_api_commands.py`, `tests/test_engine_commands.py`
  - 참고 초안 없이 `docs/명세.md` 4절 기준으로 만듦
  - 요청: `senior_id, text, program_id?`(지금 보는 방송, 없으면 지금 시각의 하루표 칸) / 응답: `intent, reply, needs_confirm, done, schedule_changed, channel_id?`
  - 말 해석 순서: ① LLM 에게 명령 7개(`skip_today, exclude, pin, rest_day, undo, change_channel, question`) 중 **한 단어만** 고르게 함 (기본 fake) → ② 못 고르거나 오류면 단어 규칙 → ③ `exclude`·`pin` 은 바로 저장 안 하고 확인 질문
  - 확인 질문 대기: 서버 메모리에 어르신별 "대기 중인 명령" 1개. 다음 말이 "응/네/그래"면 저장, "아니"면 취소, 다른 말이면 대기 버리고 새 명령으로 처리
  - undo = 그 어르신의 **마지막 켜진 규칙** `active=False`. change_channel = 응답에 `channel_id` 만 (시청 기록은 C 담당)
  - 테스트(먼저): 명령 7개 해석 표, `test_llm_choice_is_used_when_valid`, `test_bad_llm_answer_falls_back_to_word_rules`, `test_exclude_asks_before_saving`, 흐름 `test_exclude_confirm_hide_then_undo_brings_back`
  - 끝 기준: s1 "이거 이제 안 볼래" → 확인 질문 → "응" → 사라짐 → "방금 거 취소" → 다시 나옴
  - 확인 화면에서 볼 것: 말하기 칸에 위 순서대로 입력, 하루표에서 그 방송이 사라졌다 다시 나옴
  - main.py 에 넣을 줄: `from .api.commands import router as commands_router` / `app.include_router(commands_router)`

- [ ] **④ 질문 답하기 기초** (`intent=question`)
  - 고칠 파일: `engine/answer.py`(새로), `api/commands.py`, `tests/test_engine_answer.py`
  - 방식: 질문에서 때(지금/아침/낮/저녁/밤/다음)를 찾아 **하루표·편성표에서 사실 목록**을 먼저 뽑음 → 진짜 LLM 이면 "이 목록 안에서만 답, 없으면 모른다고" 지시와 함께 전달 / fake 면 사실 목록을 문장 틀로 답 / 사실이 없으면 "그건 잘 모르겠어요"
  - 테스트(먼저): `test_evening_question_lists_evening_schedule`, `test_unknown_question_says_dont_know`, `test_llm_gets_only_schedule_facts`
  - 끝 기준: "오늘 저녁에 뭐 해?" → 하루표 내용이 들어간 답
  - 확인 화면에서 볼 것: 말하기 칸에 "오늘 저녁에 뭐 해?" → 답에 저녁 칸 방송 이름·시각

- [ ] **⑤ 실시간 알림** (하루표 바뀌면 WebSocket `schedule.updated`)
  - 고칠 파일: `api/events.py`(새로: 알림 모음 — 구독·보내기, WebSocket 주소 `/ws/events`), `api/commands.py`(바뀌면 보내기), `contracts/ws.py`(`ScheduleUpdated` = `{senior_id, date}` 추가만) → `pnpm gen`, `api/views/schedule_view.html`(받으면 새로고침), `tests/test_api_events.py`
  - 테스트(먼저): `test_command_that_changes_schedule_sends_schedule_updated`, `test_command_without_change_sends_nothing`
  - 끝 기준: 창 2개 열고 한쪽에서 명령 → 다른 쪽 자동 갱신
  - 확인 화면에서 볼 것: s1 화면 2개, 한쪽에서 "다른 거 틀어 줘" → 다른 창 하루표가 저절로 바뀜
  - main.py 에 넣을 줄: `from .api.events import router as events_router` / `app.include_router(events_router)` (C 의 `/ws` 에 합칠지는 C 와 상의)

- [ ] **⑥ 가상 시계** (`GET/POST /api/clock`)
  - 고칠 파일: `api/clock.py`(새로: 지금 가상 시각 = 기준 시각 + 흐른 실제 시간 × 속도), `api/commands.py`·`api/schedules.py`(시각·날짜를 시계에서), `contracts/rest.py`(`ClockState{now, speed}`·`ClockSetRequest{now?, speed?}` 추가만) → `pnpm gen`, `docs/명세.md` 5절 + 한 줄 "가상 시계: 서버 `/api/clock` 이 기준, C 화면은 이걸 사용"(공통), `api/views/schedule_view.html`(시계 칸), `tests/test_api_clock.py`
  - 시계 값의 주인은 서버(B). C 화면은 이 API 를 보여 주고 조작만
  - 기본값: 2026-12-01 06:00, 속도 1. `date` 없이 하루표를 부르면 시계의 날짜
  - 테스트(먼저): `test_clock_moves_with_speed`(가짜 실제 시계 주입), `test_set_clock_changes_now`, `test_rest_day_uses_clock_time`
  - 끝 기준: 시계를 20:00 으로 → "오늘은 그만 볼래" → 20:00 이후 칸만 사라짐
  - 확인 화면에서 볼 것: 시계 칸에 20:00 입력 → 말하기 "오늘은 그만 볼래" → 20:00 이후 시작 칸만 없어짐
  - main.py 에 넣을 줄: `from .api.clock import router as clock_router` / `app.include_router(clock_router)`, `/ws` 의 `ClockTick` 시각을 `clock.now()` 로 (C 담당 "가상 시계"와 겹침 → C 에게 알림)
  - ⏸ 끝나면 **중간 합치기**

- [ ] **⑦ 스냅샷 테스트** (s1~s3 의 12/1 하루표 저장, 달라지면 무엇이 바뀌었는지 보여 줌)
  - 고칠 파일: `tests/test_engine_snapshot.py`, `tests/snapshots/schedule_s1.json`~`s3`(새 폴더, 허용됨)
  - 비교 칸: 시작·끝·채널·제목·kind·점수(소수 3자리)·이유. 다르면 "추가/빠짐/바뀜" 줄 목록으로 실패 메시지
  - 일부러 바꿀 때 갱신: `cd backend && uv run python tests/test_engine_snapshot.py`
  - 끝 기준: 숫자 하나(예: THRESHOLD) 바꾸면 어떤 칸이 바뀌었는지 읽을 수 있게 실패, 갱신 명령 후 통과
  - 확인 화면에서 볼 것: (화면 변화 없음) 스냅샷 파일과 확인 화면 s1~s3 표가 같은지

- [ ] **⑧ 인수인계 정리** (기능 변경 없이 — 스냅샷이 그대로여야 함)
  - 고칠 파일: `engine/*.py`, `api/{schedules,commands,events,clock}.py`, `engine/README.md`(새로), `tests/test_engine*.py`(규칙별 파일로 나눔: `test_engine_preference.py`, `test_engine_scoring.py`, `test_engine_rules.py`, `test_engine_planner.py`, `test_engine_reason.py`, `test_engine_sample.py`)
  - 이름·역할 정리, 안 쓰는 코드·중복 제거, 함수 한 가지 일, 파일 맨 위 2~3줄 설명, DP·반감기 쉬운 주석
  - README: 30초 요약 / 흐름 그림 / 파일별 역할 표 / 용어집 / 규칙 바꾸는 법(숫자=`config.py`, 규칙=`rules.py`, 장르=`genre_map.json`, 바꾼 뒤 `pnpm test`·스냅샷·확인 화면) / 처음 온 사람 30분 체험 순서
  - 끝 기준: 스냅샷 그대로 + README 30분 체험을 처음부터 따라 해서 성공한 결과 보고
  - 확인 화면에서 볼 것: 하루표가 ⑦ 때와 똑같음

- [ ] **⑨ 엔진 규칙 추가 후보 2개 제안** (시연 효과 큰 순서, 코드 없음 — 사람이 고름)
  - 고칠 파일: 이 PLAN.md 맨 아래 "다음 후보"
  - 끝 기준: 후보 2개 각각 — 무엇이 보이나 / 고칠 파일 / 반나절 안에 되나
  - ⏸ 끝나면 **중간 합치기**

---

## A 담당용: 실제 편성표 넣을 때 맞출 것 (② 확정)
- [ ] `series_key`: 같은 프로그램 회차는 같은 값 (없으면 제목에서 "(재)"·회차 번호 뺀 제목)
- [ ] `genre` = 대표 장르 1개, `genres` = 전부(대표 장르가 맨 앞). 둘 다 표준 장르 이름으로 — `data/sample/genre_map.json` 의 `synonyms` 로 바꾸고, 장르가 없거나 모르는 이름이면 제목에 `title_keywords` 가 있는지로 추정 (엔진은 모르는 장르를 0점으로 처리할 뿐 오류는 안 남)
- [ ] `cast`: 모르면 빈 목록 `[]` (엔진이 출연자 항목을 빼고 계산)
- [ ] `is_new`·`is_live`: 모르면 `false`
- [ ] `start`·`end`: 한국 시간, 시간대 표기 없이. 자정 넘는 방송은 `end` 를 다음 날로
- [ ] `channel_id` 는 `channels.json` 에 있는 값

## 진행 기록
| 날짜 | 작업 | 커밋 | 확인 화면 |
| --- | --- | --- | --- |
| 2026-11-26 | 계획 작성·승인 (기본값 6개 OK), main 합치기 | ef9bc7e | — |
| 2026-11-26 | ① 취침 전 시작 허용 + 아침 빈 시간 LG. Codex: 심각한 문제 없음. 변화: s1 20:00 왕중왕(0.806) → 21:00 별의 노래(0.865)로 바뀜(겹쳐서 점수 높은 쪽) | 766769e | /api/schedules/s1/view, s3/view |
| 2026-11-26 | ② 장르 여러 개·출연자 없음 ÷0.75·배치 무게 (점수−기준점)(결정 D)·옛 DB 안내. Codex: D 추천 / 옛 DB 오류·기준점 예외 문서 누락 지적 → 반영, 재리뷰 심각한 문제 없음 | 9487ea6 | /api/schedules/s1/view (장르 요약 3개, 21:00 별의 노래) |

## 다음 후보 (⑨에서 채움)
