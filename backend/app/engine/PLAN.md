# B 담당 작업 계획 (하루표 엔진 · 음성 명령 · 질문 답하기)

> 목표: 하루표 엔진·API 를 **시연 가능한 상태**로 끝내고, 처음 온 개발자도 이어받을 수 있게 정리.
> 진행: 작업 1개씩 "다음" → 테스트 먼저(TDD) → Codex 리뷰 → 반영 → `pnpm test` → 커밋·push(engine/rules) → 여기 체크 + 진행 기록.
> 확인 화면: `pnpm dev:be` 후 http://localhost:8000/api/schedules/s1/view (s2·s3 는 주소의 s1 만 바꿈)
> 현재 PR: **#5** (engine/realistic → main, draft) · 이전 PR #3 (①·②) 합쳐짐 11/26

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
- 11/27: ②-2 다양성은 방식 2(시간 예산 DP + 넘친 장르 무게 깎아 다시 배치), 2시간짜리 최애 새 회차는 "오늘의 대표 방송" 1편 예외(결정 다)
- `make_sample.py` 수정은 ②에 한해 허용, `tests/snapshots/` 허용, `commands_draft.py` 없이 약속 4절 기준, 가상 시계는 B 가 `api/clock.py` 로

## 지킬 것 (모든 작업 공통)
- 고칠 수 있음: `backend/app/engine/*`, `backend/app/api/{schedules,commands,events,clock}.py`, `backend/app/api/views/*`, `backend/tests/test_engine*.py`, `backend/tests/test_api_*.py`
- 공통 파일은 작업에 적힌 것만 (config 숫자, `docs/약속.md`, `app/models/db.py`, `data/sample/*`, `contracts/rest.py`·`ws.py` 추가만, `pnpm gen` 결과). 고치기 전 `gh pr list` 로 같은 파일 고치는 PR 확인 → 3줄 보고에 "공통 변경 있음, 단톡 알림 필요"
- `main.py` 는 안 고침 → "main.py 에 넣을 줄"로 보고
- LLM 은 `app/llm` 의 `make_llm(settings)` 만 사용 (기본 fake, test 프로필은 네트워크 없음)
- 커밋 전: `pnpm test` + `cd backend && uv run ruff check . && uv run ruff format --check .`
- 새 코드는 처음부터 ⑧ 기준: 파일 맨 위 "이 파일이 하는 일" 2~3줄, 함수는 한 가지 일, 이름만 봐도 역할이 보이게

---

## 작업 목록

- [x] **① 엔진 규칙 2개 변경** (취침 전 "시작"이면 허용 / 기상~첫 방송 빈 시간 채우기)
  - 고칠 파일: `engine/planner.py`, `engine/config.py`(필요 시 숫자), `api/schedules.py`(확인 화면의 "빠진 이유" 판정도 같은 규칙으로 — 엔진 함수를 같이 쓰게 해서 중복 제거), `docs/약속.md` 5·6절("기상~취침 안" 문구), `tests/test_engine.py`
  - 규칙: 후보 = `기상 ≤ 시작 < 취침` (끝나는 시간 무관). 기상~첫 칸 사이 빈 시간: 20분 미만 비움(앞 채널이 없으니 fill 안 함), 20분 이상 LG채널·VOD 중 점수 최고 1개
  - 테스트(먼저): `test_show_starting_before_sleep_is_allowed_even_if_it_ends_after`, `test_show_starting_at_or_after_sleep_is_not_allowed`, `test_morning_gap_of_20min_or_more_gets_lg_content_at_wake_time`, `test_morning_gap_under_20min_stays_empty`
  - 끝 기준: s1 에 "별의 노래 21:00" 들어감, s1·s3 아침 첫 칸이 기상 후 20분 안에 시작
  - 확인 화면에서 볼 것: s1 표 맨 아래 21:00 별의 노래, s1·s3 표 맨 위 칸 시작 시각 = 기상 시각 근처(LG 콘텐츠)

- [x] **② 외부 편성표 호환** (장르 여러 개, 출연자 없는 방송, 빠진 칸)
  - 고칠 파일: `models/db.py`(programs·watch_logs 에 `genres: list[str]` 추가, 기본 `[]`. 기존 `genre` = 대표 장르로 유지), `engine/preference.py`, `engine/scoring.py`, `engine/rules.py`, `backend/scripts/make_sample.py`(②에 한해 허용, 공통) → 다시 만든 `data/sample/programs.json`·`watch_logs.json`(일부 방송에 장르 2개), `data/sample/genre_map.json`(새 파일), `docs/약속.md` 2·6절, `tests/test_engine.py`
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

- [x] **②-2 하루표 현실화** (11/26 추가, ③ 전에. 엔진 규칙 · 테스트 먼저 · 숫자는 `config.py` · `docs/약속.md` 6절 갱신 — 공통 변경)
  - 방식: **시간 예산 DP + 넘친 장르 무게 깎아 다시 배치** (방식 2 — 실험·Codex 비교 결과. 방식 1 "배치 후 빼고 채우기"는 s1 하루표가 0분이 되는 연쇄 삭제가 나서 탈락)
  - 고칠 파일: `engine/planner.py`(배치), `engine/preference.py`(평균 시청 시간·시청 시간대·안 본 장르), `engine/diversity.py`(새로: 장르 비율·연속 검사), `engine/novelty.py`(새로: 새로 추천 1칸), `engine/reason.py`, `engine/config.py`, `api/schedules.py`(빠진 이유), `docs/약속.md` 6절, `tests/test_engine*.py`, `tests/test_api_schedules.py`
  - 순서 (각각 테스트 먼저):
    - [x] **a. 시청 시간** (완료 11b05dd): 시청 시간대 = 시간대 습관 점수 0.35 이상인 시간대(방송 "시작" 기준, ①과 같음). pick·LG 채우기는 그 안에서만. 총 pick 시간 ≤ 최근 평균 시청 시간(본 날 7일 미만이면 240분). 배치는 1분 단위 시간 예산 DP. pin·새로 추천은 먼저 고정하고 남은 예산으로 배치
    - [x] **b. 다양성**: 같은 대표 장르 ≤ pick 시간의 50% (pin 은 분자·분모 모두 제외), 같은 장르 3칸째 연속부터 무게 ×0.7. 넘치면 그 장르 무게 ×0.7 하고 다시 DP (최대 10번). 끝까지 못 지키면 규칙을 지킨 결과 중 최고, 없으면 시간 상한은 지키고 50% 는 완화(확인 화면에 표시)
    - [x] **b-2. 오늘의 대표 방송 1편** (11/27 결정 "다"): 새 회차(is_new)이면서 시리즈 취향 점수 1위, 시청 시간대 안에서 시작하는 것만. pin 처럼 먼저 넣고 장르 50% 계산에서 빼며, 시간 상한에는 포함. reason = "오늘 꼭 챙겨 보실 ○○ 새 회차예요". 확인 화면 장르 비율은 이 1편 제외/포함 둘 다
    - [x] **c. 새로 추천 1칸**: 가장 좋아하는 장르와 가까운 장르(`config.NEAR_GENRES`) 중 시청 기록상 거의 안 본 장르(시청 시간 비율 < 5%)의 방송 1개 (배치 뒤 남은 자리, 없으면 LG). "안 볼래"로 뺀 시리즈·장르는 절대 안 고름. kind 는 pick 그대로, reason = "새로 추천해 드려요 — …"
    - [x] **d. 빠진 이유**: 확인 화면에 "시청 시간대 밖", "시간 상한", "다양성" 추가 — 엔진이 배치하면서 남긴 기록으로 표시 (따로 다시 계산하지 않음)
  - 테스트(먼저): `test_viewing_hours_are_bands_with_habit_score_over_min`, `test_daily_budget_is_recent_average_or_240_when_few_days`, `test_total_pick_minutes_stay_within_budget`, `test_lg_fill_only_inside_viewing_hours`, `test_one_genre_takes_at_most_half_of_pick_time`, `test_pinned_shows_are_left_out_of_genre_share`, `test_third_same_genre_in_a_row_is_penalized`, `test_novelty_picks_unseen_genre_near_favorite`, `test_novelty_never_picks_excluded_series_or_genre`, `test_view_shows_diversity_and_budget_reasons`
  - 끝 기준: s1 하루표가 트로트 50% 이하 + "새로 추천" 1칸 + 총 시간이 평균 시청 시간 근처. s2·s3 도 한 장르 도배 없음
  - 확인 화면에서 볼 것: s1 표 맨 위 요약(총 pick 시간 / 상한, 장르 비율), "새로 추천해 드려요" 칸, "빠진 방송"에 다양성·시간 상한 이유

    - [x] **e. 기준표 v3** (11/27): `QUALITY.md`(M1~M7 반드시, S1~S9 목표, 가치 지표) + `quality.py` 판정 + 확인 화면 맨 위 표시 + 페르소나 6명 테스트(`tests/test_engine_quality.py`)
    - [x] **f. 첫날 정보**: `pref_source` = child > self > none (age_default 삭제), 샘플 s3 = 자녀가 고른 관심사 3개 + 기록 거의 없음, 관심사 바꾸면 다음 하루표에 바로 반영, 관심사·기록 둘 다 없으면 새 회차·생방송만 + "관심사를 고르면 더 잘 맞춰요"

- [ ] **③ 음성 명령 API** (`POST /api/commands`, 약속 4절) + 확인 화면에 말하기 칸
  - 고칠 파일: `api/commands.py`(새로: 요청 받기·응답), `engine/commands.py`(새로: 말 해석 + 규칙 저장/취소), `contracts/rest.py`(`CommandRequest`·`CommandResponse` 추가만) → `pnpm gen`, `docs/약속.md` 4·5절, `api/views/schedule_view.html`(말하기 칸), `tests/test_api_commands.py`, `tests/test_engine_commands.py`
  - 참고 초안 없이 `docs/약속.md` 4절 기준으로 만듦
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
  - 추가(11/26): "지금 뭐 볼까?" → 현재 가상 시각 기준으로 지금 하거나 곧 시작하는 방송 중 점수 높은 1~3개 추천 (`test_what_to_watch_now_recommends_up_to_three_from_clock_time`)
  - 끝 기준: "오늘 저녁에 뭐 해?" → 하루표 내용이 들어간 답 / "지금 뭐 볼까?" → 지금 시각 기준 1~3개
  - 확인 화면에서 볼 것: 말하기 칸에 "오늘 저녁에 뭐 해?" → 답에 저녁 칸 방송 이름·시각

- [ ] **⑤ 실시간 알림** (하루표 바뀌면 WebSocket `schedule.updated`)
  - 고칠 파일: `api/events.py`(새로: 알림 모음 — 구독·보내기, WebSocket 주소 `/ws/events`), `api/commands.py`(바뀌면 보내기), `contracts/ws.py`(`ScheduleUpdated` = `{senior_id, date}` 추가만) → `pnpm gen`, `api/views/schedule_view.html`(받으면 새로고침), `tests/test_api_events.py`
  - 테스트(먼저): `test_command_that_changes_schedule_sends_schedule_updated`, `test_command_without_change_sends_nothing`
  - 끝 기준: 창 2개 열고 한쪽에서 명령 → 다른 쪽 자동 갱신
  - 확인 화면에서 볼 것: s1 화면 2개, 한쪽에서 "다른 거 틀어 줘" → 다른 창 하루표가 저절로 바뀜
  - main.py 에 넣을 줄: `from .api.events import router as events_router` / `app.include_router(events_router)` (C 의 `/ws` 에 합칠지는 C 와 상의)

- [ ] **⑥ 가상 시계** (`GET/POST /api/clock`)
  - 고칠 파일: `api/clock.py`(새로: 지금 가상 시각 = 기준 시각 + 흐른 실제 시간 × 속도), `api/commands.py`·`api/schedules.py`(시각·날짜를 시계에서), `contracts/rest.py`(`ClockState{now, speed}`·`ClockSetRequest{now?, speed?}` 추가만) → `pnpm gen`, `docs/약속.md` 5절 + 한 줄 "가상 시계: 서버 `/api/clock` 이 기준, C 화면은 이걸 사용"(공통), `api/views/schedule_view.html`(시계 칸), `tests/test_api_clock.py`
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

## 결정 기록 (②-2, 11/27 — 원칙: 1 시연 안정성 2 되돌리기 쉬움 3 설명 가능 4 단순 5 데이터 없으면 보수적)
| # | 무엇 | 왜 | Codex 의견 | 다른 선택지 |
| --- | --- | --- | --- | --- |
| D1 | 출연자 정보 없음 = 출연자 칸 0 (`MISSING_CAST_SCORE`, ②의 ÷0.75 보정 철회) **의견 갈림** | S7(출연자 지워도 ±0.02)을 테스트로 지킬 수 있는 유일한 안, "모르는 출연자와 같음"이 설명 쉬움(3), 숫자 하나로 되돌림(2) | 보정 유지하고 S7 실패 표시 | 평균 대입 / 보정 유지 |
| D2 | 대표 방송 = 전체 시리즈 취향 1위(0.5 이상)가 오늘 시청 시간대에 새 회차일 때만 | 문구 그대로·근거 약하면 안 넣음(5) | 같음 | 오늘 새 회차 중 1위 |
| D3 | 같은 시리즈 하루 1번 = DP 전에 시리즈마다 무게 최대 회차 1개만 | 확실·단순(4) | 같음 | DP 후 감점 반복 |
| D4 | 채널 유지 = DP 뒤 앞 칸 채널 후보로 바꾸기(가산 0.05), 다른 기준이 나빠지면 취소 | 계산 구조를 안 키움(4) | 같음 | DP 상태에 채널 추가 |
| D5 | 첫 칸 30분(S6) = 하루 첫 시청 구간만 | 낮은 순위 목표로 칸을 늘리지 않음(5) | 같음 | 시청 구간마다 |
| D6 | LG 30% = LG 시간 ÷ 하루표 전체 시간, 점수 높은 것부터 | 앞 시간대 약한 LG 가 한도를 먼저 쓰지 않게 | 같음 | 시간 순 |
| D7 | M2 챙겨 줘 100% = 기상~취침 시작 + 겹치면 점수 높은 쪽(동점 시작→ID) 확정분 전부 | 겹치는 둘을 다 넣을 수 없음 | 같음 | — |
| D8 | 빠진 이유 = 조건을 하나씩 끈 배치와 비교 (예산만/다양성만) | 감점 사실만으로 단정하면 M5(근거 일치)에 어긋남 | (b) 같음 — 처음 내 안(a, 감점 여부로 단정)에서 바꿈 | 감점 여부로 단정 |
| D9 | s1 대표 방송(120분)이 상한 107분 넘어도 넣고 S3 실패 표시 | 기준표 우선순위 S1 > S3 | 같음 | — |
| D10 | 취향을 모르면 새 회차·생방송만 후보 **의견 갈림** | 요청 문구 그대로 + M5(이유 "새로 하는 방송 위주" 근거 일치) | 점수(시간대+새 회차)대로 두기 | 점수대로 |
| D11 | 새로 추천 LG 1개는 S9 취향 점수 기준 예외 (`NOVELTY_LG_SKIPS_SCORE_RULE`) | 안 본 장르라 점수가 낮아 기준표의 "LG 에서" 대체안이 쓰일 수 없음. LG 30% 는 그대로 | 같음 | 기준표 그대로(S5 항상 실패) |
| D12 | LG 배정 순서 = 새로 추천 → 첫 시청 구간(S6) → 점수순 | S9 조건 안에서 첫 칸이 비는 일 줄임 | 같음 | 점수순만 |
| D13 | 새로 추천 방송은 배치(DP) **뒤** 남은 시간·자리에만 | 처음엔 먼저 넣었더니 순위 낮은 S5 가 취향 방송 예산을 빼앗음(보편형 페르소나 하루표가 대표+새로 추천뿐) | (자체 판단, 테스트로 발견) | 먼저 넣기 |
| D14 | 3연속(S4) 감점은 줄 전체 / 장르 비율(S2)은 셀 칸 2개 이상일 때만 | 3칸째만 깎으면 "가운데를 바꾸는" 답을 못 찾음, 1칸이면 항상 100% | (자체 판단, 테스트로 발견) | — |
| D15 | 하루 시간 상한 = chosen 기록만 (`BUDGET_SIGNALS`) | 기준표 S3 문구 그대로 | — | 이어짐·추천 포함 |

## A 담당 메모 (가족 화면)
- [ ] 설치 때 **자녀가 부모님 관심사(장르 2~3개, 좋아하는 프로그램·출연자)를 고르는 화면** → `seniors.pref_source = "child"`, `seed_prefs`
- [ ] **관심사 변경 화면** (바꾸면 다음 하루표에 바로 반영됨 — 엔진이 매번 다시 계산)
- [ ] 기본 장르는 두지 않음: 아무것도 안 고르면 `pref_source = "none"`, 엔진이 새 회차·생방송 위주로 짜고 "관심사를 고르면 더 잘 맞춰요" 안내

## C 담당 메모 (TV 화면)
- [ ] **오늘의 대표 방송 10분 전 알림** (하루표 칸 중 이유가 "오늘 꼭 챙겨 보실 ○○ 새 회차예요"인 칸 — 필요하면 B 가 응답에 표시 칸 추가를 별도 PR 로)

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
| 2026-11-26 | PR #3(①·②) 합쳐짐 → 새 브랜치 engine/realistic, draft PR #5. ②-2 추가, 방식 비교(방식 2 채택 예정). Codex: 방식 2 추천 + pin 먼저 고정·종료 정책·빠진 이유 정확히 | — | — |
| 2026-11-27 | ②-2a 시청 시간대·하루 시청 시간 상한(1분 단위 예산 DP)·pin 먼저 고정. s1 510→210분(상한 224), s3 240분. 아직 장르 도배(s1 트로트·s2 뉴스 100%)는 b 에서. Codex: 심각한 문제 없음 | 11b05dd | /api/schedules/s1/view (요약에 하루표 시간/상한·시청 시간대) |
| 2026-11-27 | ②-2 b~f 기준표 v3 (대표 방송·다양성·LG 기준·채널 유지·새로 추천·첫 칸·첫날 정보) — 공통 변경. 샘플 3명·페르소나 6명 M1~M7 통과. Codex: 결정 15개 비교(갈림 2: D1·D10), 리뷰 4회(pin 충돌·같은 시리즈 pin·새로 추천의 S2·S4 위반 → 반영), 구간 전체 리뷰 심각한 문제 없음 | a0c849b | /api/schedules/s1/view (맨 위 기준표·가치 지표) |

## 다음 후보 (⑨에서 채움)
