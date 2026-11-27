"""전후 비교: 두 git 버전의 엔진으로 같은 사례를 돌려 기준표 M·S 통과표와 가치 지표를 표로 보여 준다.

- 사례 = 지금 작업 폴더의 테스트 페르소나(tests/test_engine_quality.py) 전부 + 샘플 3명(s1~s3) + 무작위 200개 요약.
  입력(페르소나·샘플·무작위 예시)은 두 버전 모두 지금 작업 폴더 것, 판정은 각 버전의 quality.py (다르면 경고)
- 기준 버전(기본 origin/jinhyeok)은 임시 폴더에 git worktree 로 꺼내서 돌리고, 끝나면 지운다
- 나빠진 S(전엔 통과·해당 없음 → 지금 실패)는 빨간색 (--md 면 🔴)

사용: cd backend && uv run python -m app.engine.compare [--base origin/jinhyeok] [--head 다른버전] [--md]
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
MUST = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"]
GOALS = ["S1", "S2", "S3", "S9", "S10", "S8", "S4", "S5", "S6"]
METRICS = [("taste_match", "취향일치", "{:.0%}"), ("lg_minutes", "LG분", "{}"), ("switches", "전환", "{}")]
RED, END = "\033[31m", "\033[0m"


# ───────── 한 버전 돌리기 (그 버전 폴더를 맨 앞 import 경로로 두고 따로 실행됨) ─────────


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _report_json(report) -> dict:
    return {
        "must": {c: report.must[c].ok for c in MUST if c in report.must},
        "goals": {c: report.goals[c].ok for c in GOALS if c in report.goals},
        "metrics": {k: report.metrics.get(k) for k, _, _ in METRICS},
    }


def run_version(engine_root: Path, cases_root: Path) -> dict:
    """engine_root 의 엔진(app/)으로 cases_root 의 사례를 돌린 결과."""
    from datetime import date

    import app.models.sample as sample_module

    # 입력을 같게: 두 버전 모두 지금 작업 폴더의 샘플을 읽음 (페르소나 모듈이 import 할 때 이 값을 가져감)
    sample_dir = cases_root.parent / "data" / "sample"
    sample_module.SAMPLE_DIR = sample_dir
    cases = _load("eval_cases_quality", cases_root / "tests" / "test_engine_quality.py")
    rnd = _load("eval_cases_random", cases_root / "tests" / "test_engine_random.py")
    out: dict = {"cases": {}, "random": {}}
    for name in cases.PERSONAS:
        try:
            out["cases"][name] = _report_json(cases.persona_plan(name)[1])
        except Exception as ex:  # noqa: BLE001 — 옛 엔진이 새 사례를 못 돌리면 멈추지 말고 표에 "오류"로 남김
            out["cases"][name] = {"error": f"{type(ex).__name__}: {ex}"}
    out["cases"].update(_sample_seniors(sample_dir, date(2026, 12, 1)))

    must_fail, goal_fail = dict.fromkeys(MUST, 0), dict.fromkeys(GOALS, 0)

    @rnd.on_random_days  # 테스트와 같은 시드 → 같은 200개
    def collect(case):
        report = rnd.run_case(case)
        for fails, checks in ((must_fail, report.must), (goal_fail, report.goals)):
            for code, check in checks.items():
                if check.ok is False and code in fails:
                    fails[code] += 1

    collect()
    out["random"] = {"n": rnd.EXAMPLES, "must_fail": must_fail, "goal_fail": goal_fail}
    return out


def _sample_seniors(sample_dir: Path, day) -> dict:
    from app.engine.service import plan_day
    from app.models.db import init_db, make_engine, make_session_factory
    from app.models.sample import load_sample

    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        engine = make_engine(Path(tmp) / "compare.db")
        init_db(engine)
        with make_session_factory(engine)() as session:
            load_sample(session, sample_dir)
            for sid in ("s1", "s2", "s3"):
                out[f"샘플 {sid}"] = _report_json(plan_day(session, sid, day)[1])
        engine.dispose()
    return out


# ───────── 두 버전 비교 ─────────


def _git(*args: str, cwd: Path = BACKEND) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _run_in(backend_root: Path) -> dict:
    """그 버전 폴더에서 이 파일을 '한 버전 돌리기' 모드로 실행 (사례는 지금 작업 폴더 것)."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--run-version", str(backend_root), str(BACKEND)],
        check=False,  # 실패하면 아래에서 stderr 를 보여 줌
        cwd=backend_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{backend_root} 에서 실행 실패:\n{proc.stderr[-3000:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def collect_both(base: str, head: str | None) -> tuple[dict, dict, str, str]:
    """기준 버전과 지금(또는 head 버전)의 결과. worktree 는 끝나면 지운다."""
    with tempfile.TemporaryDirectory() as tmp:
        trees = []
        try:
            roots = {}
            for label, ref in (("base", base), ("head", head)):
                if ref is None:
                    roots[label] = BACKEND
                    continue
                path = Path(tmp) / label
                _git("worktree", "add", "--detach", str(path), ref)
                trees.append(path)
                roots[label] = path / "backend"
            return (
                _run_in(roots["base"]),
                _run_in(roots["head"]),
                f"{base} ({_git('rev-parse', '--short', base)})",
                f"{head} ({_git('rev-parse', '--short', head)})" if head else "지금 작업 폴더",
            )
        finally:
            for path in trees:
                _git("worktree", "remove", "--force", str(path))


def judge_changed(base: str, head: str | None) -> bool:
    """판정 코드(quality.py)가 두 버전에서 다른가. 다르면 표의 차이에 '판정 기준 변경'이 섞여 있음."""
    refs = [base] if head is None else [base, head]  # head 가 없으면 지금 작업 폴더와 비교
    path = str(BACKEND / "app" / "engine" / "quality.py")
    return (
        subprocess.run(["git", "diff", "--quiet", *refs, "--", path], cwd=BACKEND, check=False).returncode
        != 0
    )


def _mark(ok) -> str:
    return {True: "✔", False: "✘", None: "·"}[ok]


def _worse(old, new) -> bool:
    return new is False and old is not False


def _cell(old, new, red: str, end: str) -> str:
    text = _mark(new) if old == new else f"{_mark(old)}→{_mark(new)}"
    return f"{red}{text}{end}" if _worse(old, new) else text


def _must_text(res: dict) -> str:
    if "error" in res:
        return "오류"
    bad = [c for c in MUST if res["must"].get(c) is False]
    return "✔" if not bad else "✘" + ",".join(bad)


def _metric_text(old: dict, new: dict, key: str, fmt: str) -> str:
    a, b = (r.get("metrics", {}).get(key) for r in (old, new))
    show = lambda v: "-" if v is None else fmt.format(v)
    return show(b) if a == b else f"{show(a)}→{show(b)}"


def _random_row(old: dict, new: dict, red: str, end: str) -> list[str]:
    """무작위 예시 요약 한 줄: M 실패 합계 + S 코드별 실패 개수 (늘었으면 빨간색)."""

    def count(part: str, code: str) -> str:
        a, b = old[part].get(code, 0), new[part][code]
        text = str(b) if a == b else f"{a}→{b}"
        return f"{red}{text}{end}" if b > a else text

    m_old, m_new = sum(old["must_fail"].values()), sum(new["must_fail"].values())
    must = f"✘ {m_new}건" if m_new else "✔ 0건"
    return [
        f"무작위 {new['n']}개 (실패 수)",
        must if m_old == m_new else f"{m_old}→{must}",
        *(count("goal_fail", c) for c in GOALS),
        *([""] * len(METRICS)),
    ]


def table(base: dict, head: dict, md: bool) -> list[str]:
    red, end = ("🔴", "") if md else (RED, END)
    header = ["사례", "M", *GOALS, *(title for _, title, _ in METRICS)]
    rows = []
    for name in head["cases"]:
        old, new = base["cases"].get(name, {"error": "기준 버전에 없음"}), head["cases"][name]
        m_old, m_new = _must_text(old), _must_text(new)
        goals = [
            "오류"
            if "error" in old or "error" in new
            else _cell(old["goals"].get(c), new["goals"].get(c), red, end)
            for c in GOALS
        ]
        metrics = [_metric_text(old, new, key, fmt) for key, _, fmt in METRICS]
        rows.append([name, m_new if m_old == m_new else f"{m_old}→{m_new}", *goals, *metrics])
    rows.append(_random_row(base["random"], head["random"], red, end))
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + [
        "| " + " | ".join(r) + " |" for r in rows
    ]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) == 4 and sys.argv[1] == "--run-version":  # 한 버전 돌리기 모드
        engine_root = Path(sys.argv[2])
        sys.path[0] = str(engine_root)  # 이 파일 폴더 대신 그 버전의 backend/ 를 import 경로 맨 앞에
        print(json.dumps(run_version(engine_root, Path(sys.argv[3]))))
        return
    parser = argparse.ArgumentParser(description="두 버전의 하루표 엔진 기준표 비교")
    parser.add_argument("--base", default="origin/jinhyeok", help="기준 버전 (기본 origin/jinhyeok)")
    parser.add_argument("--head", default=None, help="비교할 버전 (기본: 지금 작업 폴더)")
    parser.add_argument("--md", action="store_true", help="마크다운 표로 (PR 본문용, 빨간색 대신 🔴)")
    args = parser.parse_args()
    base, head, base_name, head_name = collect_both(args.base, args.head)
    print(f"기준: {base_name}  →  지금: {head_name}")
    print("입력: 두 버전 모두 지금 작업 폴더의 페르소나·샘플·무작위 예시 / 판정: 각 버전의 quality.py")
    if judge_changed(args.base, args.head):
        print("⚠ 판정 코드(quality.py)가 두 버전에서 다름 — 아래 차이에 '판정 기준 변경'이 섞여 있음")
    print("✔ 통과 · 해당 없음 ✘ 실패 | 나빠진 S 는 " + ("🔴" if args.md else f"{RED}빨간색{END}"))
    print("\n".join(table(base, head, args.md)))


if __name__ == "__main__":
    main()
