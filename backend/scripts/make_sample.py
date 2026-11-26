"""공통 샘플 데이터 만들기 → data/sample/*.json

실행: (backend 폴더에서) uv run python scripts/make_sample.py
- 방송 이름·출연자·편성 시각은 전부 **가상** (실제 편성표는 A 담당이 1단계에서 넣음)
- 시각은 한국 시간, 시간대 표기 없이 "YYYY-MM-DDTHH:MM:SS"
- 같은 씨앗(seed)이라 몇 번을 돌려도 같은 결과가 나온다
"""

import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "sample"
DAY = date(2026, 12, 1)  # 시연 기준일 (화요일)
HISTORY_DAYS = 14

CHANNELS = [  # (id, 번호, 이름) — 번호는 예시. 실제 번호표는 A 담당
    ("KBS1", 9, "KBS1"),
    ("KBS2", 7, "KBS2"),
    ("MBC", 11, "MBC"),
    ("SBS", 5, "SBS"),
    ("EBS1", 13, "EBS1"),
    ("TVC", 19, "TV조선"),
]

# 채널별 하루 편성: (시작, 제목, series_key, 장르, 출연자, 새 회차, 생방송). 끝 = 다음 칸 시작, 마지막은 24:00
N, L, R = "new", "live", ""  # 표기 줄이기
LINEUP: dict[str, list[tuple]] = {
    "KBS1": [
        ("05:00", "새벽 뉴스", "kbs1-news-dawn", "뉴스", [], L),
        ("06:00", "아침 뉴스", "kbs1-news-am", "뉴스", [], L),
        ("08:00", "아침 사랑방", "kbs1-sarangbang", "교양", ["박미숙", "이철호"], L),
        ("09:30", "건강 백세", "kbs1-health100", "건강", ["강민수"], N),
        ("10:30", "고향 한 바퀴", "kbs1-hometown", "교양", ["이철호"], R),
        ("11:30", "동물 이야기", "kbs1-animal", "다큐", [], R),
        ("12:00", "정오 뉴스", "kbs1-news-noon", "뉴스", [], L),
        ("13:00", "트로트 대잔치", "kbs1-trot-party", "트로트", ["송미란", "김태호"], R),
        ("14:30", "다큐 세상", "kbs1-docu", "다큐", [], R),
        ("15:30", "인생 극장", "kbs1-life", "교양", [], N),
        ("16:30", "어르신 노래교실", "kbs1-songclass", "트로트", ["송미란"], N),
        ("17:30", "고향 한 바퀴", "kbs1-hometown", "교양", ["이철호"], N),
        ("19:00", "저녁 뉴스", "kbs1-news-pm", "뉴스", [], L),
        ("20:30", "일일드라마 햇살 가득", "kbs1-haetsal", "드라마", ["한지수", "오민재"], N),
        ("21:30", "사극 왕의 길", "kbs1-king", "사극", ["정대현", "윤서아"], N),
        ("22:40", "밤 시사 토론", "kbs1-debate", "시사", [], L),
        ("23:40", "마감 뉴스", "kbs1-news-night", "뉴스", [], L),
    ],
    "KBS2": [
        ("05:00", "꽃피는 마을 (재)", "kbs2-flower", "드라마", ["한지수"], R),
        ("06:30", "아침 생활 정보", "kbs2-info-am", "교양", [], L),
        ("08:30", "아침드라마 봄날의 약속", "kbs2-spring", "드라마", ["이은정"], N),
        ("09:10", "생활의 지혜", "kbs2-wisdom", "교양", [], R),
        ("10:30", "꽃피는 마을 (재)", "kbs2-flower", "드라마", ["한지수"], R),
        ("12:00", "요리 한 상", "kbs2-cook", "요리", ["최영자"], N),
        ("13:00", "고전 명작 영화", "kbs2-movie", "영화", [], R),
        ("15:00", "노래 경연 왕중왕 (재)", "kbs2-king-of-song", "트로트", ["김태호", "송미란"], R),
        ("17:00", "퀴즈 한마당", "kbs2-quiz", "예능", [], N),
        ("18:00", "스포츠 하이라이트", "kbs2-sports", "스포츠", [], N),
        ("19:00", "저녁 생활 정보", "kbs2-info-pm", "교양", [], L),
        ("20:00", "노래 경연 왕중왕", "kbs2-king-of-song", "트로트", ["김태호", "송미란"], N),
        ("21:30", "드라마 사랑의 계절", "kbs2-season", "드라마", ["오민재"], N),
        ("22:50", "웃음 충전", "kbs2-laugh", "예능", [], N),
    ],
    "MBC": [
        ("05:00", "새벽 뉴스", "mbc-news-dawn", "뉴스", [], L),
        ("06:00", "생방송 아침", "mbc-morning", "교양", [], L),
        ("08:00", "아침드라마 바람의 언덕", "mbc-hill", "드라마", ["윤서아"], N),
        ("08:40", "오늘의 건강", "mbc-health", "건강", ["강민수"], N),
        ("10:00", "시골 밥상 (재)", "mbc-countryfood", "요리", ["최영자"], R),
        ("11:00", "자연 다큐", "mbc-nature", "다큐", [], R),
        ("12:00", "정오 뉴스", "mbc-news-noon", "뉴스", [], L),
        ("13:00", "사극 조선의 별 (재)", "mbc-joseon", "사극", ["정대현"], R),
        ("15:00", "트로트 열전 (재)", "mbc-trot", "트로트", ["송미란"], R),
        ("16:30", "경제 매거진", "mbc-economy", "시사", [], N),
        ("17:30", "시골 밥상", "mbc-countryfood", "요리", ["최영자"], N),
        ("18:30", "우리 동네 이야기", "mbc-town", "교양", [], N),
        ("19:30", "저녁 뉴스", "mbc-news-pm", "뉴스", [], L),
        ("20:30", "일일극 푸른 바다", "mbc-bluesea", "드라마", ["이은정"], N),
        ("21:30", "가족 여행", "mbc-family-trip", "예능", [], N),
        ("22:40", "시사 매거진", "mbc-current", "시사", [], N),
        ("23:40", "마감 뉴스", "mbc-news-night", "뉴스", [], L),
    ],
    "SBS": [
        ("05:00", "새벽 뉴스", "sbs-news-dawn", "뉴스", [], L),
        ("06:00", "모닝 와이드", "sbs-wide", "교양", [], L),
        ("08:30", "아침드라마 두 번째 봄", "sbs-second-spring", "드라마", ["이은정"], N),
        ("09:10", "생활 백서", "sbs-life-book", "교양", [], R),
        ("10:20", "동물 친구들 (재)", "sbs-animal", "다큐", [], R),
        ("12:00", "정오 뉴스", "sbs-news-noon", "뉴스", [], L),
        ("13:00", "스포츠 매거진", "sbs-sports", "스포츠", [], N),
        ("14:00", "오후의 영화", "sbs-movie", "영화", [], R),
        ("16:00", "트로트 스타 (재)", "sbs-trotstar", "트로트", ["김태호"], R),
        ("17:30", "생방송 오늘 저녁", "sbs-tonight", "교양", [], L),
        ("19:00", "동물 친구들", "sbs-animal", "다큐", [], N),
        ("20:00", "저녁 뉴스", "sbs-news-pm", "뉴스", [], L),
        ("21:00", "드라마 비밀의 정원", "sbs-garden", "드라마", ["한지수"], N),
        ("22:20", "웃음 공장", "sbs-laugh", "예능", [], N),
        ("23:30", "나이트 뉴스", "sbs-news-night", "뉴스", [], L),
    ],
    "EBS1": [
        ("05:00", "세계 테마 여행 (재)", "ebs-world", "다큐", [], R),
        ("06:00", "어르신 체조", "ebs-exercise", "건강", [], N),
        ("07:00", "다큐 프라임 (재)", "ebs-prime", "다큐", [], R),
        ("08:00", "명의 건강 (재)", "ebs-doctor", "건강", ["강민수"], R),
        ("09:00", "세계 테마 여행 (재)", "ebs-world", "다큐", [], R),
        ("11:00", "한국 기행", "ebs-korea", "교양", [], R),
        ("12:00", "요리 비결", "ebs-cook", "요리", [], R),
        ("13:00", "명의 건강 (재)", "ebs-doctor", "건강", ["강민수"], R),
        ("14:00", "바둑 한 판", "ebs-baduk", "취미", [], N),
        ("15:00", "한국 기행", "ebs-korea", "교양", [], N),
        ("16:00", "어르신 체조 (재)", "ebs-exercise", "건강", [], R),
        ("17:00", "다큐 프라임 (재)", "ebs-prime", "다큐", [], R),
        ("19:00", "세계 테마 여행", "ebs-world", "다큐", [], N),
        ("20:00", "극한 직업", "ebs-extreme", "다큐", [], N),
        ("21:00", "명의 건강", "ebs-doctor", "건강", ["강민수"], N),
        ("22:00", "다큐 프라임", "ebs-prime", "다큐", [], N),
        ("23:00", "고전 영화", "ebs-movie", "영화", [], R),
    ],
    "TVC": [
        ("05:00", "새벽 뉴스", "tvc-news-dawn", "뉴스", [], L),
        ("07:00", "시사 아침", "tvc-current-am", "시사", [], L),
        ("09:00", "트로트 쇼 (재)", "tvc-trotshow", "트로트", ["송미란", "김태호"], R),
        ("11:00", "건강 정보 쇼", "tvc-health", "건강", ["강민수"], R),
        ("12:30", "정오 뉴스", "tvc-news-noon", "뉴스", [], L),
        ("13:30", "트로트 쇼 (재)", "tvc-trotshow", "트로트", ["송미란", "김태호"], R),
        ("15:30", "역사 이야기", "tvc-history", "다큐", [], R),
        ("16:30", "트로트 오디션 별의 노래 (재)", "tvc-star", "트로트", ["김태호", "송미란"], R),
        ("18:00", "시사 판", "tvc-current-pm", "시사", [], L),
        ("19:30", "저녁 뉴스", "tvc-news-pm", "뉴스", [], L),
        ("21:00", "트로트 오디션 별의 노래", "tvc-star", "트로트", ["김태호", "송미란"], N),
        ("23:00", "트로트 쇼 (재)", "tvc-trotshow", "트로트", ["송미란", "김태호"], R),
    ],
}

# 대표 장르 말고 더 붙는 장르 (외부 편성표처럼 장르가 여러 개인 방송). 이름은 data/sample/genre_map.json 의 표준 장르
EXTRA_GENRES: dict[str, list[str]] = {
    "kbs1-sarangbang": ["예능"],
    "kbs1-health100": ["교양"],
    "kbs1-hometown": ["다큐"],
    "kbs1-trot-party": ["예능"],
    "kbs1-songclass": ["교양"],
    "kbs1-king": ["드라마"],
    "kbs2-cook": ["예능"],
    "kbs2-king-of-song": ["예능"],
    "mbc-health": ["교양"],
    "mbc-countryfood": ["교양"],
    "mbc-joseon": ["드라마"],
    "mbc-trot": ["예능"],
    "sbs-trotstar": ["예능"],
    "ebs-doctor": ["교양"],
    "ebs-korea": ["다큐"],
    "tvc-trotshow": ["예능"],
    "tvc-health": ["교양"],
    "tvc-star": ["예능"],
}

SENIORS = [
    {
        "id": "s1",
        "name": "김영숙",
        "age": 75,
        "wake_time": "06:00",
        "sleep_time": "22:00",
        "pref_source": "child",  # 자녀가 첫날 입력
        "seed_prefs": {
            "series": ["kbs1-haetsal", "tvc-star"],
            "cast": ["송미란"],
            "genres": ["트로트", "드라마"],
        },
        "family_picks": ["kbs1-life"],
    },
    {
        "id": "s2",
        "name": "박철수",
        "age": 80,
        "wake_time": "05:30",
        "sleep_time": "21:30",
        "pref_source": "self",  # 본인이 카드 고르기
        "seed_prefs": {"series": ["kbs1-king"], "cast": ["정대현"], "genres": ["뉴스", "사극", "시사"]},
        "family_picks": [],
    },
    {
        "id": "s3",
        "name": "이순자",
        "age": 70,
        "wake_time": "06:30",
        "sleep_time": "22:30",
        "pref_source": "age_default",  # 정보 없음 → 나이대 기본값 (콜드 스타트)
        "seed_prefs": {"series": [], "cast": [], "genres": ["교양", "건강", "트로트"]},
        "family_picks": ["ebs-doctor"],
    },
]

# 시청 기록 만들 때 어르신별로 잘 보는 것 (가중치) · 싫어하는 것 (반응)
HABITS = {
    "s1": {
        "like": {
            "kbs1-haetsal": 5,
            "tvc-star": 4,
            "kbs1-songclass": 3,
            "kbs2-king-of-song": 3,
            "mbc-bluesea": 2,
        },
        "dislike": {"kbs1-debate": "next", "mbc-current": "next"},
        "per_day": (3, 5),
    },
    "s2": {
        "like": {"kbs1-king": 5, "kbs1-news-pm": 5, "kbs1-news-am": 3, "tvc-current-pm": 3, "ebs-baduk": 2},
        "dislike": {"kbs2-laugh": "help", "sbs-laugh": "help"},
        "per_day": (3, 5),
    },
    "s3": {"like": {"ebs-doctor": 2, "kbs1-hometown": 2}, "dislike": {}, "per_day": (0, 1)},
}


def _dt(d: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day) + timedelta(hours=h, minutes=m)


def day_programs(d: date) -> list[dict]:
    out = []
    for ch, rows in LINEUP.items():
        for i, (start, title, key, genre, cast, flag) in enumerate(rows):
            end = _dt(d, rows[i + 1][0]) if i + 1 < len(rows) else _dt(d, "00:00") + timedelta(days=1)
            out.append(
                {
                    "id": f"{ch}-{d:%Y%m%d}-{start.replace(':', '')}",
                    "channel_id": ch,
                    "title": title,
                    "series_key": key,
                    "genre": genre,
                    "genres": [genre, *EXTRA_GENRES.get(key, [])],
                    "start": _dt(d, start).isoformat(),
                    "end": end.isoformat(),
                    "cast": cast,
                    "is_new": flag == N,
                    "is_live": flag == L,
                }
            )
    return out


def watch_logs(rng: random.Random) -> list[dict]:
    logs = []
    for offset in range(HISTORY_DAYS, 0, -1):
        d = DAY - timedelta(days=offset)
        progs = day_programs(d)
        for senior in SENIORS:
            h = HABITS[senior["id"]]
            if senior["id"] == "s3" and offset > 3:  # 콜드 스타트: 최근 3일만 조금
                continue
            liked = [p for p in progs if p["series_key"] in h["like"]]
            weights = [h["like"][p["series_key"]] for p in liked]
            n = rng.randint(*h["per_day"])
            chosen = {p["id"]: p for p in rng.choices(liked, weights, k=n)} if liked and n else {}
            for p in chosen.values():
                dur = (datetime.fromisoformat(p["end"]) - datetime.fromisoformat(p["start"])).seconds / 60
                how = rng.choices(["chosen", "plan", "continued"], [6, 2, 2])[0]
                logs.append(_log(senior["id"], p, rng.uniform(0.6, 1.0) * dur, "none", how))
            # 싫어하는 것: 잠깐 보다가 "다음에"/"됐다"
            for key, fb in h["dislike"].items():
                if rng.random() < 0.3:
                    p = next(p for p in progs if p["series_key"] == key)
                    logs.append(_log(senior["id"], p, rng.uniform(1, 4), fb, "continued"))
            # 채널 돌리다 잠깐 (5분 미만 → 취향 계산에서 무시돼야 함)
            if rng.random() < 0.5:
                p = rng.choice(progs)
                logs.append(_log(senior["id"], p, rng.uniform(0.5, 4.5), "none", "chosen"))
            # 틀어만 놓고 집안일 (이어서 켜진 채 오래) → 엔진은 약하게만 반영해야 함
            if senior["id"] != "s3" and rng.random() < 0.3:
                p = rng.choice([p for p in progs if p["series_key"] not in h["like"]])
                dur = (datetime.fromisoformat(p["end"]) - datetime.fromisoformat(p["start"])).seconds / 60
                logs.append(_log(senior["id"], p, dur, "none", "continued"))
    logs.sort(key=lambda x: (x["started_at"], x["senior_id"]))
    return logs


def _log(senior_id: str, p: dict, minutes: float, feedback: str, how_started: str) -> dict:
    return {
        "senior_id": senior_id,
        "channel_id": p["channel_id"],
        "series_key": p["series_key"],
        "genre": p["genre"],
        "genres": p["genres"],
        "cast": p["cast"],
        "started_at": p["start"],
        "watched_min": round(minutes, 1),
        "feedback": feedback,
        "how_started": how_started,
        "cancelled": False,
    }


# 빈 시간(20분 이상)에 끼울 LG채널·VOD 콘텐츠 (가상)
LG_CONTENTS = [
    ("lg-trot-1", "LG채널 트로트 명곡 모음", "트로트", ["송미란"], 30, "LG채널"),
    ("lg-trot-2", "LG채널 트로트 라이브", "트로트", ["김태호"], 60, "LG채널"),
    ("lg-trot-3", "추억의 가요 20분", "트로트", [], 20, "LG채널"),
    ("lg-drama-1", "LG VOD 명작 드라마 1화", "드라마", ["한지수"], 50, "LG VOD"),
    ("lg-drama-2", "LG VOD 주말극 다시보기", "드라마", ["오민재"], 60, "LG VOD"),
    ("lg-health-1", "LG채널 5분 건강 체조 모음", "건강", [], 20, "LG채널"),
    ("lg-health-2", "LG채널 명의 특강", "건강", ["강민수"], 40, "LG채널"),
    ("lg-docu-1", "LG채널 세계 자연 다큐", "다큐", [], 45, "LG채널"),
    ("lg-docu-2", "LG채널 우리 땅 기행", "교양", [], 30, "LG채널"),
    ("lg-news-1", "LG채널 뉴스 요약", "뉴스", [], 20, "LG채널"),
    ("lg-history-1", "LG VOD 사극 명장면", "사극", ["정대현"], 40, "LG VOD"),
    ("lg-cook-1", "LG채널 집밥 한 그릇", "요리", ["최영자"], 25, "LG채널"),
    ("lg-baduk-1", "LG채널 바둑 명국", "취미", [], 60, "LG채널"),
    ("lg-fun-1", "LG채널 웃음 모음", "예능", [], 30, "LG채널"),
]

# 음성 명령으로 이미 생긴 규칙 (예시)
USER_RULES = [
    {
        "senior_id": "s1",
        "kind": "exclude",
        "target_type": "series",
        "target": "mbc-bluesea",
    },  # "푸른 바다 이제 안 볼래"
    {
        "senior_id": "s2",
        "kind": "pin",
        "target_type": "series",
        "target": "kbs1-news-pm",
    },  # "저녁 뉴스 매일 챙겨 줘"
]

# 하루표 API 응답 예시 (모양 약속용. 엔진 결과가 아님) — s1 김영숙
EXAMPLE_PICKS = [
    ("KBS1", "09:30", "pick", "아침에 보기 좋은 건강 정보예요"),
    ("KBS1", "13:00", "pick", "송미란 님이 나오는 트로트예요"),
    ("KBS1", "15:30", "pick", "가족이 추천한 프로그램이에요"),
    ("KBS1", "16:30", "pick", "좋아하시는 트로트 새 회차예요"),
    ("KBS1", "17:30", "fill", "채널을 그대로 두고 이어서 봐요"),
    ("KBS1", "20:30", "pick", "매일 보시는 드라마 새 회차예요"),
]  # 취침(22:00) 전에 끝나고, 서로 겹치지 않게


def schedule_example(progs: list[dict]) -> dict:
    by = {(p["channel_id"], p["start"][11:16]): p for p in progs}
    number = {c[0]: c[1] for c in CHANNELS}
    items = []
    for ch, start, kind, reason in EXAMPLE_PICKS:
        p = by[(ch, start)]
        items.append(
            {
                "program_id": p["id"],
                "channel_id": ch,
                "channel_number": number[ch],
                "title": p["title"],
                "start": p["start"],
                "end": p["end"],
                "score": 0.0 if kind == "fill" else 0.5,
                "reason": reason,
                "kind": kind,
            }
        )
    return {"senior_id": "s1", "date": DAY.isoformat(), "items": items}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    progs = day_programs(DAY)
    files = {
        "channels.json": [{"id": i, "number": n, "name": name} for i, n, name in CHANNELS],
        "programs.json": progs,
        "seniors.json": SENIORS,
        "watch_logs.json": watch_logs(random.Random(42)),
        "schedule_example.json": schedule_example(progs),
        "lg_contents.json": [
            {"id": i, "title": t, "genre": g, "cast": c, "duration_min": d, "source": src}
            for i, t, g, c, d, src in LG_CONTENTS
        ],
        "user_rules.json": USER_RULES,
    }
    for name, data in files.items():
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"data/sample/ 에 {len(files)}개 파일 생성 (편성 {len(progs)}편, 시청 기록 {len(files['watch_logs.json'])}건)"
    )


if __name__ == "__main__":
    main()
