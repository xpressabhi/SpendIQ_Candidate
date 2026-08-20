"""Golden evaluation set: tiered questions with composable checks.

Each case runs through the real agent (LLM included) via `run_agent`.
Checks are deterministic where the data supports it (counts, entity
names, tool use, cited sources) and optionally LLM-judged for
qualitative answers (run with `--judge`).

Expected facts are grounded in the ingested dataset — run `make ingest`
first. They are pinned here so regressions in retrieval, the analytic
SQL views, or prompting show up as failing cases.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalCase:
    id: str
    tier: str
    question: str
    checks: tuple = field(default_factory=tuple)


def contains(*needles: str, any_: bool = False) -> dict:
    kind = "contains_any" if any_ else "contains_all"
    return {"type": kind, "values": [n.lower() for n in needles]}


def not_contains(*needles: str) -> dict:
    return {"type": "contains_none", "values": [n.lower() for n in needles]}


def tool(name: str) -> dict:
    return {"type": "tool_used", "value": name}


def source(doc_id: str) -> dict:
    return {"type": "source_cited", "value": doc_id}


def regex(pattern: str, description: str) -> dict:
    return {"type": "regex", "pattern": pattern, "description": description}


NUMBER_WORDS = {
    "4": ("four",),
    "5": ("five",),
    "9": ("nine",),
    "10": ("ten",),
    "11": ("eleven",),
    "12": ("twelve",),
    "20": ("twenty",),
    "47": ("forty-seven", "forty seven"),
    "60": ("sixty",),
    "90": ("ninety",),
}


def count_near(number: str, keyword: str) -> dict:
    """Pass if `number` (digits or spelled out) appears near `keyword`
    in either order, case-insensitive."""
    alts = [number, *NUMBER_WORDS.get(number, ())]
    num = rf"\b(?:{'|'.join(alts)})\b"
    pattern = (
        rf"{num}(?=[^.]{{0,80}}\b{keyword})"
        rf"|\b{keyword}\D{{0,80}}{num}"
    )
    return regex(pattern, f"mentions '{number}' near '{keyword}'")


def judge(rubric: str) -> dict:
    return {"type": "llm_judge", "rubric": rubric}


CASES = [
    EvalCase(
        "stratos_12mo", "T1",
        "What is our total spend with Stratos Cloud Services over the last 12 months?",
        (contains("882,050", "882050", any_=True), tool("query_structured_data")),
    ),
    EvalCase(
        "top10_ytd", "T1",
        "Who are our top 10 vendors by year-to-date spend?",
        (contains("Nimbus Advisors", "Aperture"), tool("query_structured_data")),
    ),
    EvalCase(
        "active_by_category", "T1",
        "How many active contracts do we have, broken down by contract type?",
        (
            contains("subscription", "retainer", "blanket po", "sow"),
            count_near("47", "contract"),
            tool("query_structured_data"),
        ),
    ),
    EvalCase(
        "orion_renewal", "T2",
        "Summarize the auto-renewal terms for our Orion Logistics contract.",
        (
            contains(
                "not automatically renew", "does not automatically renew",
                "no automatic renewal", "not auto-renew",
                "does not auto-renew", "no auto-renew", any_=True,
            ),
            count_near("90", "day"),
            source("CTR-0003"),
            tool("retrieve_documents"),
        ),
    ),
    EvalCase(
        "aperture_notice", "T2",
        "What notice period is required to exit the Aperture SaaS subscription?",
        (
            count_near("60", "day"),
            source("CTR-0013"),
            tool("retrieve_documents"),
        ),
    ),
    EvalCase(
        "split_policy", "T2",
        "What does our procurement policy say about splitting purchase orders?",
        (
            contains("prohibited"),
            source("POL-procurement_policy"),
            tool("retrieve_documents"),
        ),
    ),
    EvalCase(
        "auto_renew_90d", "T3",
        "Which contracts auto-renew in the next 90 days and what is the notice window for each?",
        (
            count_near("9", "contract"),
            contains("CTR-0001", "CTR-0014", "CTR-0057", any_=True),
            tool("query_structured_data"),
        ),
    ),
    EvalCase(
        "terms_mismatch", "T3",
        "Find invoices whose billed payment terms are shorter than the terms stated in the underlying contract.",
        (
            contains("INV-001560", "INV-001561", "INV-001562", "INV-001563"),
            tool("query_structured_data"),
        ),
    ),
    EvalCase(
        "split_pos", "T3",
        "Identify purchase orders that appear to have been split to stay under approval thresholds.",
        (
            contains(
                "PO-01950", "PO-01945", "PO-01947", "PO-01941", "PO-01943"
            ),
            tool("query_structured_data"),
        ),
    ),
    EvalCase(
        "no_contract_50k", "T3",
        "Which vendors have more than USD 50,000 in year-to-date spend but no active contract?",
        (
            count_near("20", "vendor"),
            contains("Aperture Industries", "Osprey Corp", "Summit Group", any_=True),
            tool("query_structured_data"),
        ),
    ),
    EvalCase(
        "over_cap", "T4",
        "Flag contracts where cumulative invoice spend has exceeded the stated total contract value cap.",
        (
            count_near("11", "contract"),
            contains("CTR-0002", "CTR-0008", "CTR-0014", any_=True),
            tool("query_structured_data"),
        ),
    ),
    EvalCase(
        "duplicate_invoices", "T4",
        "Surface duplicate-looking invoices from the same vendor in the last six months.",
        (
            count_near("10", "invoice"),
            contains("INV-000038", "INV-000071", "INV-000266", any_=True),
            tool("query_structured_data"),
        ),
    ),
    EvalCase(
        "renegotiation_brief", "T4",
        "Draft a one-paragraph renegotiation brief for the three vendors where we have the most leverage (highest spend, contract expiring, no auto-renew protection).",
        (
            contains("Redwood"),
            tool("query_structured_data"),
            judge(
                "Pass if the answer names Redwood Industries among the top-leverage "
                "vendors, gives its contract expiry around 2026-04-24 with a 30-day "
                "notice window, and cites spend around $1,162,250. Fail if it names a "
                "different top vendor, omits the deadline, or invents figures."
            ),
        ),
    ),
    EvalCase(
        "leverage_top", "T4",
        "Which vendor has the most leverage in our favor right now, and what is the exact notice deadline if we want to exit their contract?",
        (
            contains("Redwood"),
            contains(
                "2026-04-24", "april 24, 2026", "april 24 2026", "april 24",
                "24 april 2026", "2026-03-25", "march 25", "3 days",
                any_=True,
            ),
            tool("query_structured_data"),
        ),
    ),
]
