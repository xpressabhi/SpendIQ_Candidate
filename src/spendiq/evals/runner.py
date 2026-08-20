"""Eval runner CLI: executes the golden set through the agent and grades it.

Usage:
  make eval                          # all tiers, deterministic checks only
  uv run python -m spendiq.evals --tier T1
  uv run python -m spendiq.evals --case split_pos
  uv run python -m spendiq.evals --judge          # also run LLM-judge checks
  uv run python -m spendiq.evals --runs 3         # majority vote per case
  uv run python -m spendiq.evals --json data/eval_report.json

`--runs N` runs each case N times (fresh thread each run) and passes a
check if it passes in at least `--pass-rate` of the executed runs. This
absorbs LLM phrasing variance while still catching real regressions
(those fail 100% of runs).

Exit code: 0 if every executed check passes, 1 on any failure/agent
error, 2 on bad usage. Requires `make ingest` first (the agent reads
the SQLite DB and FTS index).
"""

import argparse
import json
import sys
import time

from ..agent import _build_llm, run_agent
from ..config import MOCK
from ..db import DB_PATH
from . import graders
from .cases import CASES

_MARKS = {True: "✓", False: "✗", None: "?"}


def _run_case_once(case, judge_llm, run_index: int) -> dict:
    row = {
        "id": case.id, "tier": case.tier, "question": case.question,
        "checks": [], "elapsed_s": None, "status": "ok",
    }
    t0 = time.time()
    try:
        result = run_agent(
            [{"role": "user", "content": case.question}],
            f"eval-{case.id}-{run_index}",
        )
    except Exception as exc:
        row["elapsed_s"] = round(time.time() - t0, 1)
        row["status"] = "error"
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row
    row["elapsed_s"] = round(time.time() - t0, 1)
    row["answer"] = result["answer"]
    row["tools"] = [t["name"] for t in result["tools"]]
    row["sources"] = result["sources"]
    for check in case.checks:
        entry = {
            "type": check["type"],
            "detail": (
                check.get("description")
                or check.get("value")
                or check.get("rubric", "")[:80]
                or (check.get("values") or [""])[0]
            ),
        }
        if check["type"] == "llm_judge" and judge_llm is None:
            entry["ok"] = None
            entry["detail"] = "judge disabled (run with --judge)"
        else:
            try:
                ok, detail = graders.run_check(
                    check, result["answer"], result, judge_llm, case.question
                )
                entry["ok"] = ok
                entry["detail"] = detail
            except Exception as exc:
                entry["ok"] = False
                entry["detail"] = f"grader error: {exc}"
        row["checks"].append(entry)
    return row


def _aggregate(case, per_run: list[dict], pass_rate: float) -> dict:
    """Merge N per-case runs into one row with per-check pass counts."""
    row = {
        "id": case.id, "tier": case.tier, "question": case.question,
        "runs": len(per_run), "pass_rate": pass_rate,
        "elapsed_s": round(sum(r["elapsed_s"] or 0 for r in per_run), 1),
        "status": "error" if any(r["status"] == "error" for r in per_run) else "ok",
    }
    if row["status"] == "error":
        errs = [r.get("error", "unknown error") for r in per_run
                if r["status"] == "error"]
        row["error"] = "; ".join(errs)
    good_run = next((r for r in per_run if r["status"] == "ok"), None)
    if good_run:
        row["answer"] = good_run["answer"]
        row["tools"] = good_run["tools"]
        row["sources"] = good_run["sources"]
    checks = []
    for i, check in enumerate(case.checks):
        outcomes = []
        for r in per_run:
            if r["status"] != "ok":
                continue
            r_checks = r.get("checks", [])
            if i >= len(r_checks):
                outcomes.append(False)
            else:
                outcomes.append(r_checks[i].get("ok"))
        executed = [o for o in outcomes if o is not None]
        passed = sum(1 for o in executed if o)
        entry = {
            "type": check["type"],
            "detail": (
                check.get("description")
                or check.get("value")
                or check.get("rubric", "")[:80]
                or (check.get("values") or [""])[0]
            ),
            "runs_passed": passed,
            "runs_total": len(executed),
        }
        if not executed:
            entry["ok"] = None
        else:
            entry["ok"] = passed / len(executed) >= pass_rate
        checks.append(entry)
    row["checks"] = checks
    return row


def run_evals(cases, judge: bool = False, limit: int | None = None,
              runs: int = 1, pass_rate: float = 0.5) -> list[dict]:
    judge_llm = _build_llm() if judge else None
    if judge and MOCK:
        print("warning: SPENDIQ_MOCK=1 — llm_judge checks cannot run")
        judge_llm = None
    rows = []
    for case in (cases[:limit] if limit else cases):
        if runs > 1:
            per_run = [_run_case_once(case, judge_llm, i) for i in range(runs)]
            rows.append(_aggregate(case, per_run, pass_rate))
        else:
            rows.append(_run_case_once(case, judge_llm, 0))
    return rows


def _case_status(row: dict) -> str:
    if row["status"] == "error":
        return "ERROR"
    if any(c["ok"] is False for c in row["checks"]):
        return "FAIL"
    return "PASS"


def _print_report(rows: list[dict]) -> list[str]:
    for row in rows:
        status = _case_status(row)
        runs = f", {row['runs']} runs" if row.get("runs", 1) > 1 else ""
        print(f"\n=== [{row['tier']}] {row['id']} — {status} "
              f"({row['elapsed_s']}s{runs})")
        print(f"    Q: {row['question']}")
        if row["status"] == "error":
            print(f"    ! agent error: {row['error']}")
            continue
        for c in row["checks"]:
            tally = ""
            if c.get("runs_total", 0) > 1:
                tally = f" [{c['runs_passed']}/{c['runs_total']} runs]"
            print(f"    {_MARKS[c['ok']]} {c['type']}: {c['detail']}{tally}")
        if status != "PASS" and "answer" in row:
            print(f"    answer: {row['answer'][:400]}")
    by_tier: dict[str, dict] = {}
    failed = []
    for row in rows:
        bucket = by_tier.setdefault(row["tier"], {"pass": 0, "total": 0})
        bucket["total"] += 1
        if _case_status(row) == "PASS":
            bucket["pass"] += 1
        else:
            failed.append(row["id"])
    print("\nSummary:")
    for tier in sorted(by_tier):
        b = by_tier[tier]
        print(f"  {tier}: {b['pass']}/{b['total']} passed")
    total_pass = sum(b["pass"] for b in by_tier.values())
    total_cases = sum(b["total"] for b in by_tier.values())
    print(f"  Total: {total_pass}/{total_cases} passed")
    if failed:
        print(f"  Failed/errored cases: {', '.join(failed)}")
    return failed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the SpendIQ golden eval set.")
    ap.add_argument("--tier", help="only run cases in this tier (T1-T4)")
    ap.add_argument("--case", dest="case_id", help="only run the case with this id")
    ap.add_argument("--limit", type=int, help="only run the first N cases")
    ap.add_argument("--runs", type=int, default=1,
                    help="run each case N times and majority-vote the checks")
    ap.add_argument("--pass-rate", type=float, default=0.5,
                    help="min fraction of runs a check must pass (with --runs > 1)")
    ap.add_argument("--judge", action="store_true",
                    help="run llm_judge checks (requires the LLM endpoint)")
    ap.add_argument("--json", metavar="PATH",
                    help="write a machine-readable report to PATH")
    args = ap.parse_args(argv)

    if MOCK:
        print("warning: SPENDIQ_MOCK=1 — agent answers are echoes; "
              "deterministic checks will fail")
    if not DB_PATH.exists():
        print(f"warning: {DB_PATH} not found — run `make ingest` first")

    cases = [
        c for c in CASES
        if (not args.tier or c.tier == args.tier)
        and (not args.case_id or c.id == args.case_id)
    ]
    if not cases:
        print("no cases selected")
        return 2

    rows = run_evals(cases, judge=args.judge, limit=args.limit,
                     runs=args.runs, pass_rate=args.pass_rate)
    failed = _print_report(rows)

    if args.json:
        report = {
            "summary": {
                "total": len(rows), "failed": failed,
                "runs": args.runs, "pass_rate": args.pass_rate,
            },
            "cases": rows,
        }
        with open(args.json, "w") as fh:
            json.dump(report, fh, indent=2, default=str)
        print(f"\nReport written to {args.json}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
