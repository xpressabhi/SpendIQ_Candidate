"""End-to-end smoke test: runs representative questions across all four
tiers against the running agent (LLM included).

Usage:
  uv run python -m spendiq.validate            # after `make ingest` and `make run`
  SPENDIQ_MOCK=1 uv run python -m spendiq.validate   # offline, no LLM

Exits non-zero only on hard failures (no answer / crash). Answer quality
is printed for manual review.
"""

import sys
import time

from .agent import run_agent

QUESTIONS = [
    ("T1", "What is our total spend with Stratos Cloud Services over the last 12 months?"),
    ("T1", "Who are our top 10 vendors by year-to-date spend?"),
    ("T1", "How many active contracts do we have, broken down by category?"),
    ("T2", "Summarize the auto-renewal terms for our Orion Logistics contract."),
    ("T2", "What notice period is required to exit the Aperture SaaS subscription?"),
    ("T2", "What does our procurement policy say about splitting purchase orders?"),
    ("T3", "Which contracts auto-renew in the next 90 days and what is the notice window for each?"),
    ("T3", "Find invoices whose billed payment terms are shorter than the terms stated in the underlying contract."),
    ("T3", "Identify purchase orders that appear to have been split to stay under approval thresholds."),
    ("T3", "Which vendors have more than USD 50,000 in year-to-date spend but no active contract?"),
    ("T4", "Flag contracts where cumulative invoice spend has exceeded the stated total contract value cap."),
    ("T4", "Surface duplicate-looking invoices from the same vendor in the last six months."),
    ("T4", "Draft a one-paragraph renegotiation brief for the three vendors where we have the most leverage (highest spend, contract expiring, no auto-renew protection)."),
    ("T4", "Which vendor has the most leverage in our favor right now, and what is the exact notice deadline if we want to exit their contract?"),
]


def main() -> int:
    failures = 0
    for tier, question in QUESTIONS:
        t0 = time.time()
        print(f"\n=== [{tier}] {question}")
        try:
            result = run_agent([{"role": "user", "content": question}], f"validate-{tier}")
            dt = time.time() - t0
            answer = result["answer"]
            tools = ", ".join(t["name"] for t in result["tools"]) or "(none)"
            sources = ", ".join(result["sources"]) or "(none)"
            print(f"--- answer ({dt:.0f}s): {answer[:400]}")
            print(f"--- tools: {tools}")
            print(f"--- sources: {sources}")
            if not answer or "error" in answer.lower()[:50]:
                failures += 1
                print("--- !!! FAILED")
        except Exception as exc:
            failures += 1
            dt = time.time() - t0
            print(f"--- !!! ERROR after {dt:.0f}s: {exc}")
    print(f"\n{'='*70}\nDone: {len(QUESTIONS) - failures}/{len(QUESTIONS)} questions answered without error.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
