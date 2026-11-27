# 데이터 수집 설계 (A · 데이터)

> 이 폴더(`backend/app/data/`)의 작업 기준. 다른 담당이 기대는 약속(DB 칸, 채널 번호 규칙, 외부 자료 출처)은 `docs/명세.md` 에도 적는다.
> 처음 작성: 이슈 #12 (2026-11-27)

## 출처
| 순서 | 출처 | 가져오는 것 | 비고 |
| --- | --- | --- | --- |
| 기준 | U+tv 홈페이지 채널 안내 | 후보 채널, 시간표, **U+ 채널 번호** | 오늘 포함 5일치, **시작 시각만** 있음. epg2xml LG 코드 참고 (https://github.com/epg2xml/epg2xml/blob/main/epg2xml/providers/lg.py), 코드는 복사하지 않음 |
| 보강 1 | 스카이라이프 편성표 `https://www.skylife.co.kr/api/api/public/tv/schedule/YYYYMMDD` | 출연진, 세부 장르, 생방송 여부 | 같은 채널 + 가까운 시각 + 비슷한 제목으로 U+ 방송과 짝지음 |
| 보강 2 | TMDB | 시리즈 출연진(고정/게스트 구분), 인물(동명이인) 확인 | API 키는 `backend/.env` → `settings` 로만 읽음 |

## 원칙
- **수집에 수작업 없음.** 규칙으로 안 되는 빈칸·애매한 판단만 LLM이 맡는다.
- LLM 결과는 **정해진 JSON 형식**으로 받고 서버가 검사한다. 판단 결과는 저장해 같은 질문을 다시 하지 않는다.
- 테스트에서는 **가짜 LLM**, **가짜 응답**(값이 전부 가상)만 쓰고 네트워크를 쓰지 않는다.

## 흐름 (`pipeline.py`)
```
받기(sources) → 원본 저장(raw_store) → 정리(normalize) → 짝짓기(merge) → 보강(enrich) → DB 넣기(load)
```
- **매일 새벽 자동 수집.** 실행 입구는 `uv run python -m app.data --date YYYY-MM-DD` (매일 돌리는 방법은 나중에 정함)
- **실패 시**: U+ 실패 → 스카이라이프만 / 둘 다 실패 → 전날 저장본으로 진행
- U+ 는 시작 시각만 있으므로 **끝 시각 = 같은 채널 다음 방송의 시작 시각**
- 장르는 `data/sample/genre_map.json` 표준 장르로 바꾼다

## 저장 위치
| 무엇 | 어디 | Git |
| --- | --- | --- |
| 원본 응답 | `data/epg/raw/<날짜>/<출처>.json` | 올리지 않음 |
| LLM 판단 결과 | `data/epg/cache/llm_cache.json` | 올리지 않음 |
| 결과 | DB `channels`(`number` = U+ 채널 번호)·`programs` | — |

> 두 폴더는 처음 만들 때 안에 `*` 만 적힌 `.gitignore` 를 같이 만들어 Git에 안 올라가게 한다. 루트 `.gitignore` 에 넣는 건 공통 PR로 따로.

## 파일
| 파일 | 하는 일 |
| --- | --- |
| `sources/uplus.py` · `skylife.py` · `tmdb.py` | 외부 응답 받기 (아직 빈 함수) |
| `sources/fake.py` | 테스트용 가짜 응답 (전부 가상 값) |
| `raw_store.py` | 원본 저장·읽기, 가장 최근 저장본 찾기 |
| `normalize.py` | 출처별 응답 → 공통 모양(`ProgramDraft`) |
| `merge.py` | U+ ↔ 스카이라이프 짝짓기 |
| `enrich/cast.py` | TMDB 출연진·동명이인 |
| `enrich/judge.py` | LLM 판단 (형식 검사·결과 저장·가짜 LLM) |
| `load.py` | DB에 넣기 |
| `pipeline.py` · `__main__.py` | 전체 순서 · 실행 입구 |

## 남은 일 (공통 PR 필요)
- `docs/명세.md` 7절 "외부 자료 출처"에 U+tv, 스카이라이프, TMDB, epg2xml(참고) 기록 + 이용약관 확인 → **실제 수집 코드를 넣기 전에**
- `settings.py` 에 `tmdb_api_key` 추가
- 루트 `.gitignore` 에 `data/epg/raw/`, `data/epg/cache/` 추가
