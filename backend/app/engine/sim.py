"""가상 어르신 생성기 (오프라인 평가용): 숨긴 진짜 취향 → 28일 편성 → 시청 기록.

- 진짜 취향(TrueTaste)은 엔진에게 보여 주지 않는다. 엔진은 시청 기록·첫날 관심사만 받는다 (offline_eval.py)
- 시청 기록은 엔진 점수식(config 가중치)을 쓰지 않고 따로 만든다: 채널을 잘 안 바꿈 + 습관 시각 + 진짜 취향 확률 + 잡음
- 같은 seed → 같은 어르신·같은 기록 (random.Random 만 씀)
- 편성은 샘플 하루치(data/sample/programs.json)를 28일로 복제 (make_schedule). 실제 편성표로 바꿀 땐 이 함수만 바꿈
"""

import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..models.db import Program, Senior, WatchLog
from ..models.sample import SAMPLE_DIR

FIRST_DAY = date(2026, 12, 1)  # 1일째
DAYS = 28
TYPES = ["뚜렷한 취향", "고루 봄", "종일 틀어 둠", "기록 적음", "취향 바뀜", "잡음 많음"]
SPARSE_DAYS = 3  # '기록 적음' 은 평가 전 3일치만 기록
SHIFT_DAY = 15  # '취향 바뀜' 은 이날부터 다른 취향

# 하루 TV 시청 분 (연령대별 범위). 출처: 통계 보정 예정 (방송매체 이용행태조사 등 공개 통계로 맞출 것)
DAILY_MINUTES_BY_AGE = {(65, 74): (150, 300), (75, 84): (200, 360), (85, 95): (240, 420)}

# 켜짐 습관: 시각별 TV 를 켤 무게 (0~1). 아침형 / 저녁형 / 종일 틀어 둠
HABITS = {
    "아침형": {
        h: (1.0 if 6 <= h < 11 else 0.4 if 11 <= h < 14 else 0.25 if 18 <= h < 21 else 0.0) for h in range(24)
    },
    "저녁형": {
        h: (1.0 if 18 <= h < 23 else 0.3 if 7 <= h < 9 else 0.15 if 12 <= h < 14 else 0.0) for h in range(24)
    },
    "종일": {h: (1.0 if 8 <= h < 22 else 0.3 if h in (7, 22) else 0.0) for h in range(24)},
}
WAKE_SLEEP = {"아침형": ("05:30", "21:00"), "저녁형": ("07:00", "23:30"), "종일": ("06:30", "22:30")}


@dataclass
class TrueTaste:
    """숨긴 진짜 취향 (평가의 정답)."""

    genres: dict[str, float]  # 표준 장르 → 무게 (합 1)
    series: list[str]  # 좋아하는 시리즈 1~3개
    cast: list[str]  # 좋아하는 출연자 0~2명
    later_genres: dict[str, float] | None = None  # '취향 바뀜': SHIFT_DAY 부터의 장르 무게

    def genres_on(self, day_no: int) -> dict[str, float]:
        return self.later_genres if self.later_genres and day_no >= SHIFT_DAY else self.genres


@dataclass
class Behavior:
    """시청 행동 (취향과 별개)."""

    habit: str  # 아침형 / 저녁형 / 종일
    daily_minutes: float
    stickiness: float  # 방송이 끝나도 채널을 그대로 둘 확률 (continued)
    noise: float  # 취향과 상관없이 아무거나 고를 확률 (우연 시청)
    early_exit: float  # 안 맞는 방송을 5분 안에 끄거나 돌릴 확률
    plan_share: float = 0.1  # 직접 고른 시청 중 '하루표 추천으로 봄'(plan) 비율
    off_day: float = 0.07  # TV 를 안 켜는 날 (외출) 확률


@dataclass
class SimSenior:
    kind: str
    senior: Senior
    taste: TrueTaste
    behavior: Behavior
    logs: list[WatchLog] = field(default_factory=list)  # 1~28일 전부 (평가 쪽에서 나눠 씀)
    first_log_day: int = 1  # 이날부터 기록 ('기록 적음'은 평가 직전 3일)


# ───────── 편성 ─────────


def standard_genres() -> list[str]:
    data = json.loads((SAMPLE_DIR / "genre_map.json").read_text(encoding="utf-8"))
    return list(data["genres"])


def sample_day() -> list[Program]:
    rows = json.loads((SAMPLE_DIR / "programs.json").read_text(encoding="utf-8"))
    return [
        Program(**{**r, "start": datetime.fromisoformat(r["start"]), "end": datetime.fromisoformat(r["end"])})
        for r in rows
    ]


def make_schedule(
    base: list[Program] | None = None, first_day: date = FIRST_DAY, days: int = DAYS
) -> list[Program]:
    """하루치 편성을 days 일로 복제 (시리즈는 매일 반복, 날짜·ID·회차만 바꿈). 실제 편성표로 바꿀 땐 이 함수만 바꿈."""
    base = base if base is not None else sample_day()
    origin = min(p.start for p in base).date()
    out = []
    for n in range(days):
        shift = (first_day - origin) + timedelta(days=n)
        day = first_day + timedelta(days=n)
        for p in base:
            start = p.start + shift
            episode = day.isoformat() if p.episode and p.episode[:4].isdigit() else f"{n + 1}회"
            out.append(
                Program(
                    id=f"{p.channel_id}-{start:%Y%m%d-%H%M}",
                    channel_id=p.channel_id,
                    title=p.title,
                    series_key=p.series_key,
                    genre=p.genre,
                    genres=list(p.genres or []),
                    start=start,
                    end=p.end + shift,
                    cast=list(p.cast or []),
                    cast_roles=dict(p.cast_roles or {}),
                    episode=episode,
                    is_new=p.is_new,
                    is_live=p.is_live,
                )
            )
    return out


def day_no(d: date) -> int:
    return (d - FIRST_DAY).days + 1


# ───────── 어르신 만들기 ─────────


def _weights(rng: random.Random, genres: list[str], focus: int | None) -> dict[str, float]:
    """장르 무게: focus 개 장르에 몰림 (None 이면 고르게)."""
    if focus is None:
        raw = {g: rng.uniform(0.7, 1.3) for g in genres}
    else:
        top = rng.sample(genres, focus)
        raw = {g: (rng.uniform(3.0, 6.0) if g in top else rng.uniform(0.0, 0.3)) for g in genres}
    total = sum(raw.values())
    return {g: v / total for g, v in raw.items()}


def _top(weights: dict[str, float], k: int) -> list[str]:
    return [g for g, _ in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def make_senior(kind: str, seed: int, schedule: list[Program]) -> SimSenior:
    """유형 kind 의 가상 어르신 1명 (seed 고정 → 항상 같음)."""
    rng = random.Random(f"{kind}-{seed}")
    genres = standard_genres()
    aired = sorted({g for p in schedule for g in (p.genres or [p.genre])})
    focus = {"뚜렷한 취향": 2, "고루 봄": None}.get(kind, rng.choice([2, 3]))
    weights = _weights(rng, aired, focus)
    weights = {g: weights.get(g, 0.0) for g in genres}
    later = None
    if kind == "취향 바뀜":  # 다른 장르로 옮겨 감 (전의 1위는 거의 안 봄)
        old_top = _top(weights, 2)
        later = _weights(rng, [g for g in aired if g not in old_top], 2)
        later = {g: later.get(g, 0.0) for g in genres}
    liked_genres = later or weights
    by_series = {p.series_key: p for p in schedule if p.start.date() == FIRST_DAY}
    series_pool = sorted(k for k, p in by_series.items() if liked_genres.get(p.genre, 0) > 0.05) or sorted(
        by_series
    )
    series = rng.sample(series_pool, min(len(series_pool), rng.randint(1, 3)))
    cast_pool = sorted({c for p in by_series.values() for c in p.cast})
    cast = rng.sample(cast_pool, rng.randint(0, min(2, len(cast_pool))))

    habit = {"종일 틀어 둠": "종일"}.get(kind) or rng.choice(["아침형", "저녁형", "종일"])
    age_band = rng.choice(list(DAILY_MINUTES_BY_AGE))
    lo, hi = DAILY_MINUTES_BY_AGE[age_band]
    behavior = Behavior(
        habit=habit,
        daily_minutes=rng.uniform(lo, hi) * (1.6 if kind == "종일 틀어 둠" else 1.0),
        stickiness={"종일 틀어 둠": 0.85}.get(kind, 0.55),
        noise={"잡음 많음": 0.35}.get(kind, 0.08),
        early_exit={"잡음 많음": 0.5}.get(kind, 0.25),
    )
    seed_genres = _top(weights, 2)  # 가족이 고른 첫날 관심사 = (처음) 취향 상위 2개, 가끔 하나 틀림
    if rng.random() < 0.3:
        seed_genres[1] = rng.choice([g for g in aired if g not in seed_genres])
    wake, sleep = WAKE_SLEEP[habit]
    senior = Senior(
        id=f"sim-{kind}-{seed}",
        name=f"가상 {kind} {seed}",
        age=rng.randint(*age_band),
        wake_time=wake,
        sleep_time=sleep,
        pref_source="child",
        seed_prefs={"series": series[:1] if rng.random() < 0.5 else [], "cast": [], "genres": seed_genres},
        family_picks=[],
        fixed_breaks=[],
    )
    sim = SimSenior(kind, senior, TrueTaste(weights, series, cast, later), behavior)
    sim.logs = simulate_logs(sim, schedule, rng)
    sim.first_log_day = 22 - SPARSE_DAYS if kind == "기록 적음" else 1
    return sim


# ───────── 시청 기록 만들기 (엔진 점수식과 무관) ─────────


def _liking(p: Program, taste: TrueTaste, n: int) -> float:
    """진짜 취향으로 본 '보고 싶은 정도' (0 이상). 장르 무게 + 좋아하는 시리즈·출연자 덤."""
    g = taste.genres_on(n)
    value = max(g.get(x, 0.0) for x in (p.genres or [p.genre])) * len(g)  # 평균 장르 = 1
    if p.series_key in taste.series:
        value += 1.5
    value += 0.7 * sum(1 for c in p.cast if c in taste.cast)
    return value


def _choose(rng: random.Random, airing: list[Program], taste: TrueTaste, n: int, noise: float) -> Program:
    if rng.random() < noise:
        return rng.choice(airing)
    weights = [0.05 + _liking(p, taste, n) ** 2 for p in airing]
    return rng.choices(airing, weights=weights)[0]


def _sessions(rng: random.Random, habit: dict[int, float], minutes: float) -> list[tuple[int, int, float]]:
    """하루 시청 묶음 [(시, 분, 길이)]: 습관 무게로 시각을 고르고, 합이 하루 시청 분이 될 때까지."""
    hours = [h for h in range(24) if habit[h] > 0]
    out, left = [], minutes
    while left > 20 and len(out) < 6:
        h = rng.choices(hours, weights=[habit[x] for x in hours])[0]
        length = min(left, rng.uniform(40, 180))
        out.append((h, rng.choice([0, 0, 10, 30, 50]), length))
        left -= length
    return sorted(out)


def simulate_logs(sim: SimSenior, schedule: list[Program], rng: random.Random) -> list[WatchLog]:
    by_day: dict[date, list[Program]] = {}
    for p in schedule:
        by_day.setdefault(p.start.date(), []).append(p)
    b, logs = sim.behavior, []
    for day, progs in sorted(by_day.items()):
        n = day_no(day)
        if rng.random() < b.off_day:
            continue
        busy_until = datetime.combine(day, datetime.min.time())
        channel = None
        for h, m, length in _sessions(rng, HABITS[b.habit], b.daily_minutes * rng.uniform(0.8, 1.2)):
            t = max(datetime.combine(day, datetime.min.time()) + timedelta(hours=h, minutes=m), busy_until)
            end = t + timedelta(minutes=length)
            how = "chosen"
            while t < end:
                airing = [p for p in progs if p.start <= t < p.end]
                if not airing:
                    break
                same = [p for p in airing if p.channel_id == channel]
                if how == "continued" and same:
                    p = same[0]
                else:
                    p = _choose(rng, airing, sim.taste, n, b.noise)
                    how = "plan" if rng.random() < b.plan_share else "chosen"
                liking = _liking(p, sim.taste, n)
                if rng.random() < b.early_exit / (1 + liking):  # 안 맞으면 금방 돌림
                    watched, reason = rng.uniform(1, 4.9), "channel_change"
                else:
                    watched = (min(p.end, end) - t).total_seconds() / 60
                    reason = "completed" if p.end <= end else "power_off"
                logs.append(_log(sim.senior.id, p, t, watched, how, reason))
                channel = p.channel_id
                t += timedelta(minutes=watched)
                if reason == "channel_change":
                    how = "chosen"
                elif reason == "completed":
                    how = "continued" if rng.random() < b.stickiness else "chosen"
            busy_until = t
    return logs


def _log(senior_id: str, p: Program, t: datetime, minutes: float, how: str, reason: str) -> WatchLog:
    return WatchLog(
        senior_id=senior_id,
        channel_id=p.channel_id,
        series_key=p.series_key,
        genre=p.genre,
        genres=list(p.genres),
        cast=list(p.cast),
        started_at=t,
        watched_min=round(minutes, 1),
        feedback="none",
        how_started=how,
        cancelled=False,
        end_reason=reason,
    )


def make_population(
    n: int, seed: int = 0, schedule: list[Program] | None = None, types: list[str] | None = None
) -> list[SimSenior]:
    """모두 n 명 (유형을 돌아가며, seed 고정 → 항상 같은 사람들)."""
    schedule = schedule if schedule is not None else make_schedule()
    types = types or TYPES
    return [make_senior(types[i % len(types)], seed * 100_000 + i, schedule) for i in range(n)]
