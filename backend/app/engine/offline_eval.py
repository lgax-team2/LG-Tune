"""개인화 오프라인 평가 (숨기고 맞히기): 가상 어르신(sim.py)의 1~21일 기록으로 22~28일 하루표를 짜서,
그날 실제로 직접 고른(chosen) 시청을 얼마나 맞히는지 잰다. quality.py 의 taste_match(자기 채점)와 달리 정답이 있다.

- 엔진 경로: 메모리 DB 에 편성·기록을 넣고 service.load_inputs → build_plan (하루표 API make_schedule 과 같은 함수)
- 지표: 적중률(실제 시청 중 하루표에 있던 비율) · 정밀도(하루표 방송 칸 중 실제로 본 비율) · 장르 순위 상관(추정 vs 숨긴 취향)
  · 학습 곡선(기록 3·7·14·21일)
- 기준선: ① 평소 채널 그대로 (시각별 가장 많이 켠 채널의 방송) ② 첫날 관심사만 (기록 없이 엔진)
- 실행: cd backend && uv run python -m app.engine.offline_eval [--n 200] [--seed 0] [--workers 프로세스 수] [--md]
  (--md 는 지금도 마크다운 표라 그대로. 사람마다 나눠 여러 프로세스로 돌림, 결과는 한 프로세스와 같음)
"""

import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..models.db import (
    Channel,
    LgContent,
    Program,
    Senior,
    WatchLog,
    init_db,
    make_engine,
    make_session_factory,
)
from ..models.sample import SAMPLE_DIR
from . import config
from .planner import build_plan
from .service import load_inputs
from .sim import FIRST_DAY, TYPES, SimSenior, day_no, make_schedule, make_senior, standard_genres

EVAL_DAYS = [FIRST_DAY + timedelta(days=d) for d in range(21, 28)]  # 22~28일
HISTORY = (3, 7, 14, 21)  # 학습 곡선: 평가 직전 며칠치 기록을 주나
MAIN_HISTORY = 21


@dataclass
class Score:
    """한 사람·한 방식의 7일 합계."""

    hits: int = 0  # 하루표에 있던 실제 시청 수
    actual: int = 0  # 실제 직접 고른 시청 수
    planned: int = 0  # 하루표 방송 칸 수
    corr: float | None = None  # 장르 순위 상관 (기준선 ① 은 없음)

    @property
    def hit_rate(self) -> float | None:
        return self.hits / self.actual if self.actual else None

    @property
    def precision(self) -> float | None:
        return self.hits / self.planned if self.planned else None


@dataclass
class PersonResult:
    kind: str
    engine: dict[int, Score] = field(default_factory=dict)  # 기록 일수 → 점수
    usual_channel: Score = field(default_factory=Score)
    seed_only: Score = field(default_factory=Score)


# ───────── 정답 (실제 시청) ─────────


def watched_programs(sim: SimSenior, schedule_by_day: dict[date, list[Program]], day: date) -> set[str]:
    """그날 직접 고른(chosen) 시청 중 5분 이상 본 방송 ID."""
    out = set()
    for log in sim.logs:
        if (
            log.started_at.date() != day
            or log.how_started != "chosen"
            or log.watched_min < config.MIN_WATCH_MIN
        ):
            continue
        p = _airing(schedule_by_day[day], log.channel_id, log.started_at)
        if p is not None:
            out.add(p.id)
    return out


def _airing(progs: list[Program], channel: str, t: datetime) -> Program | None:
    return next((p for p in progs if p.channel_id == channel and p.start <= t < p.end), None)


# ───────── 기록 나누기 · DB ─────────


def history(sim: SimSenior, days: int) -> list[WatchLog]:
    """평가 직전 days 일(22일 전날까지)의 기록. '기록 적음'은 원래 3일치뿐."""
    first = max(sim.first_log_day, 22 - days)
    return [w for w in sim.logs if first <= day_no(w.started_at.date()) <= 21]


def _copy_senior(s: Senior, sid: str) -> Senior:
    return Senior(
        id=sid,
        name=s.name,
        age=s.age,
        wake_time=s.wake_time,
        sleep_time=s.sleep_time,
        pref_source=s.pref_source,
        seed_prefs=dict(s.seed_prefs),
        family_picks=list(s.family_picks),
        fixed_breaks=list(s.fixed_breaks),
    )


def _copy_log(w: WatchLog, sid: str) -> WatchLog:
    return WatchLog(
        senior_id=sid,
        channel_id=w.channel_id,
        series_key=w.series_key,
        genre=w.genre,
        genres=list(w.genres),
        cast=list(w.cast),
        started_at=w.started_at,
        watched_min=w.watched_min,
        feedback=w.feedback,
        how_started=w.how_started,
        cancelled=w.cancelled,
        end_reason=w.end_reason,
    )


def build_db(sims: list[SimSenior], schedule: list[Program], history_days: tuple[int, ...]) -> Session:
    """메모리 DB: 채널·LG(샘플) + 28일 편성 + 어르신마다 (기록 n일 사본들 + 기록 없는 사본)."""
    session = make_session_factory(_engine())()
    read = lambda name: json.loads((SAMPLE_DIR / name).read_text(encoding="utf-8"))
    session.add_all(Channel(**c) for c in read("channels.json"))
    session.add_all(LgContent(**c) for c in read("lg_contents.json"))
    session.add_all(schedule)
    for sim in sims:
        for days in history_days:
            sid = f"{sim.senior.id}@{days}"
            session.add(_copy_senior(sim.senior, sid))
            session.add_all(_copy_log(w, sid) for w in history(sim, days))
        session.add(_copy_senior(sim.senior, f"{sim.senior.id}@seed"))
    session.commit()
    return session


def _engine():
    engine = make_engine(":memory:")
    init_db(engine)
    return engine


# ───────── 하루표 · 기준선 ─────────


def engine_plan(session: Session, sid: str, day: date) -> tuple[set[str], dict[str, float]]:
    """엔진 하루표의 방송 칸 ID(pick·채널 유지, LG 제외)와 그때 추정한 장르 취향."""
    i = load_inputs(session, sid, day)
    plan = build_plan(i.programs, i.lg_contents, i.senior, i.profile, i.rules, i.day, i.numbered_channels)
    return {e.program_id for e in plan.entries if isinstance(e.source, Program)}, i.profile.genre


def usual_channel_plan(logs: list[WatchLog], progs: list[Program]) -> set[str]:
    """기준선 ①: 시각별로 기록에서 가장 오래 켠 채널 → 그 시각에 그 채널에서 시작하는 방송."""
    minutes: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for w in logs:
        minutes[w.started_at.hour][w.channel_id] += w.watched_min
    usual = {h: min(by_ch, key=lambda ch: (-by_ch[ch], ch)) for h, by_ch in minutes.items()}
    return {p.id for p in progs if usual.get(p.start.hour) == p.channel_id}


def spearman(estimate: dict[str, float], truth: dict[str, float], genres: list[str]) -> float | None:
    """장르 순위 상관 (스피어만, 같은 값은 평균 순위)."""
    xs, ys = _ranks([estimate.get(g, 0.0) for g in genres]), _ranks([truth.get(g, 0.0) for g in genres])
    n = len(genres)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (sx * sy)


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


# ───────── 평가 ─────────


def evaluate(
    sims: list[SimSenior], schedule: list[Program], history_days: tuple[int, ...] = HISTORY
) -> list[PersonResult]:
    session = build_db(sims, schedule, history_days)
    by_day: dict[date, list[Program]] = defaultdict(list)
    for p in schedule:
        by_day[p.start.date()].append(p)
    genres = standard_genres()
    results = []
    for sim in sims:
        r = PersonResult(sim.kind)
        truth = sim.taste.genres_on(22)
        main_logs = history(sim, max(history_days))
        for days in history_days:
            r.engine[days] = Score()
        for day in EVAL_DAYS:
            actual = watched_programs(sim, by_day, day)
            for days in history_days:
                planned, genre = engine_plan(session, f"{sim.senior.id}@{days}", day)
                _add(r.engine[days], planned, actual)
                if day == EVAL_DAYS[0]:
                    r.engine[days].corr = spearman(genre, truth, genres)
            _add(r.usual_channel, usual_channel_plan(main_logs, by_day[day]), actual)
            planned, genre = engine_plan(session, f"{sim.senior.id}@seed", day)
            _add(r.seed_only, planned, actual)
            if day == EVAL_DAYS[0]:
                r.seed_only.corr = spearman(genre, truth, genres)
        results.append(r)
    session.close()
    return results


def _add(score: Score, planned: set[str], actual: set[str]) -> None:
    score.hits += len(planned & actual)
    score.actual += len(actual)
    score.planned += len(planned)


def summarize(results: list[PersonResult], history_days: tuple[int, ...] = HISTORY) -> dict[str, dict]:
    """유형별(+전체) 평균: 사람마다 비율을 내고 평균 (값이 없는 사람은 뺌)."""
    groups: dict[str, list[PersonResult]] = defaultdict(list)
    for r in results:
        groups[r.kind].append(r)
        groups["전체"].append(r)
    main = max(history_days)
    out = {}
    for kind in [*TYPES, "전체"]:
        rs = groups.get(kind, [])
        if not rs:
            continue
        out[kind] = {
            "n": len(rs),
            "engine": _avg([r.engine[main] for r in rs]),
            "usual_channel": _avg([r.usual_channel for r in rs]),
            "seed_only": _avg([r.seed_only for r in rs]),
            "curve": {d: _avg([r.engine[d] for r in rs])["hit_rate"] for d in history_days},
        }
    return out


def _avg(scores: list[Score]) -> dict[str, float | None]:
    def mean(values):
        values = [v for v in values if v is not None]
        return sum(values) / len(values) if values else None

    return {
        "hit_rate": mean(s.hit_rate for s in scores),
        "precision": mean(s.precision for s in scores),
        "corr": mean(s.corr for s in scores),
        "planned_per_day": mean(s.planned / len(EVAL_DAYS) for s in scores),  # 하루 방송 칸 수
        "actual_per_day": mean(s.actual / len(EVAL_DAYS) for s in scores),  # 하루 실제 직접 고른 시청 수
    }


def people(n: int, seed: int, types: list[str] | None = None) -> list[tuple[str, int]]:
    """평가할 사람들 [(유형, 사람 seed)] — sim.make_population 과 같은 순서·seed."""
    types = types or TYPES
    return [(types[i % len(types)], seed * 100_000 + i) for i in range(n)]


def _evaluate_chunk(chunk: list[tuple[str, int]], history_days: tuple[int, ...]) -> list[PersonResult]:
    """프로세스 하나가 맡은 사람들: 같은 seed 로 다시 만들어 평가 (결과는 한 프로세스로 돌릴 때와 같음)."""
    schedule = make_schedule()
    return evaluate([make_senior(kind, s, schedule) for kind, s in chunk], schedule, history_days)


def run(
    n: int = 200,
    seed: int = 0,
    history_days: tuple[int, ...] = HISTORY,
    types: list[str] | None = None,
    workers: int | None = None,
) -> dict:
    who = people(n, seed, types)
    workers = max(1, min(workers or os.cpu_count() or 1, len(who)))
    if workers == 1:
        return summarize(_evaluate_chunk(who, history_days), history_days)
    chunks = [who[i::workers] for i in range(workers)]
    with ProcessPoolExecutor(workers) as pool:
        parts = list(pool.map(_evaluate_chunk, chunks, [history_days] * workers))
    order = {
        person: i for i, person in enumerate(who)
    }  # 사람 순서대로 다시 모음 (평균은 순서와 상관없지만 같은 출력)
    results = sorted(
        (
            (person, r)
            for chunk, part in zip(chunks, parts, strict=True)
            for person, r in zip(chunk, part, strict=True)
        ),
        key=lambda pr: order[pr[0]],
    )
    return summarize([r for _, r in results], history_days)


# ───────── 표 ─────────


def tables(summary: dict, history_days: tuple[int, ...] = HISTORY) -> list[str]:
    pct = lambda v: "-" if v is None else f"{v:.0%}"
    num = lambda v: "-" if v is None else f"{v:+.2f}"
    per = lambda v: "-" if v is None else f"{v:.1f}"
    lines = [
        f"### 유형별 (기록 {max(history_days)}일 → 22~28일 하루표: 적중률 / 정밀도 / 장르 순위 상관 / 하루 방송 칸 수)",
        (
            "| 유형 | 명 | 실제 시청/일 | 엔진 적중 | 엔진 정밀 | 엔진 장르상관 | 엔진 칸/일 "
            "| ①평소채널 적중 | ①정밀 | ①칸/일 | ②첫날관심사 적중 | ②정밀 | ②장르상관 | ②칸/일 |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for kind, s in summary.items():
        e, u, f = s["engine"], s["usual_channel"], s["seed_only"]
        lines.append(
            f"| {kind} | {s['n']} | {per(e['actual_per_day'])} | {pct(e['hit_rate'])} | {pct(e['precision'])} "
            f"| {num(e['corr'])} | {per(e['planned_per_day'])} | {pct(u['hit_rate'])} | {pct(u['precision'])} "
            f"| {per(u['planned_per_day'])} | {pct(f['hit_rate'])} | {pct(f['precision'])} | {num(f['corr'])} "
            f"| {per(f['planned_per_day'])} |"
        )
    lines += [
        "",
        "### 학습 곡선 (엔진 적중률, 평가 직전 기록 일수별)",
        "| 유형 | " + " | ".join(f"{d}일" for d in history_days) + " |",
        "|---|" + "---|" * len(history_days),
    ]
    for kind, s in summary.items():
        lines.append(f"| {kind} | " + " | ".join(pct(s["curve"][d]) for d in history_days) + " |")
    return lines


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    n = int(args[args.index("--n") + 1]) if "--n" in args else 200
    seed = int(args[args.index("--seed") + 1]) if "--seed" in args else 0
    workers = int(args[args.index("--workers") + 1]) if "--workers" in args else None
    print(f"가상 어르신 {n}명 (seed {seed}), 기록 1~21일 → 22~28일")
    print("\n".join(tables(run(n, seed, workers=workers))))


if __name__ == "__main__":
    main()
