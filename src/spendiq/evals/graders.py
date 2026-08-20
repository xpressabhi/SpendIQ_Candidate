"""Check implementations for eval cases.

Every grader is a pure function over `(check, answer, result)` where
`result` is the AgentResult dict from `run_agent`. They return
`(ok, detail)`; `ok` is None only for skipped LLM-judge checks.
"""

import json
import re


def contains_all(check: dict, answer: str, result: dict) -> tuple[bool, str]:
    needle = answer.lower()
    missing = [v for v in check["values"] if v not in needle]
    if missing:
        return False, f"missing {missing}"
    return True, f"found {len(check['values'])} expected strings"


def contains_any(check: dict, answer: str, result: dict) -> tuple[bool, str]:
    needle = answer.lower()
    hits = [v for v in check["values"] if v in needle]
    if hits:
        return True, f"found {hits[0]!r}"
    return False, f"none of {check['values']} found"


def contains_none(check: dict, answer: str, result: dict) -> tuple[bool, str]:
    needle = answer.lower()
    bad = [v for v in check["values"] if v in needle]
    if bad:
        return False, f"forbidden strings present: {bad}"
    return True, "no forbidden strings found"


def regex_check(check: dict, answer: str, result: dict) -> tuple[bool, str]:
    if re.search(check["pattern"], answer, re.IGNORECASE):
        return True, check.get("description", "pattern matched")
    return False, f"pattern {check['pattern']!r} not found"


def tool_used(check: dict, answer: str, result: dict) -> tuple[bool, str]:
    names = [t["name"] for t in result.get("tools", [])]
    if check["value"] in names:
        return True, f"tool {check['value']!r} was called"
    return False, f"tool {check['value']!r} not called (tools: {names})"


def source_cited(check: dict, answer: str, result: dict) -> tuple[bool, str]:
    hits = [s for s in result.get("sources", []) if s.startswith(check["value"])]
    if hits:
        return True, f"source {check['value']!r} cited ({hits[0]})"
    return False, f"source {check['value']!r} not in {result.get('sources')}"


JUDGE_PROMPT = """You are grading an AI copilot's answer against a rubric.
Be strict but fair. Reply with a single JSON object:
{{"pass": true, "reason": "one sentence"}}

Question: {question}
Rubric: {rubric}
Answer: {answer}"""


def _parse_judge(text: str) -> tuple[bool, str]:
    """Pull a JSON object out of a judge response (handles fences/waffle)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    else:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    data = json.loads(text)
    return bool(data["pass"]), str(data.get("reason", ""))


def llm_judge(check: dict, answer: str, result: dict,
              judge_llm=None, question: str = "") -> tuple[bool | None, str]:
    if judge_llm is None:
        return None, "judge disabled"
    prompt = JUDGE_PROMPT.format(
        question=question, rubric=check["rubric"], answer=answer[:4000]
    )
    resp = judge_llm.invoke(prompt)
    text = resp.content if hasattr(resp, "content") else str(resp)
    ok, reason = _parse_judge(text)
    return ok, reason


_GRADERS = {
    "contains_all": contains_all,
    "contains_any": contains_any,
    "contains_none": contains_none,
    "regex": regex_check,
    "tool_used": tool_used,
    "source_cited": source_cited,
}


def run_check(check: dict, answer: str, result: dict,
              judge_llm=None, question: str = "") -> tuple[bool | None, str]:
    """Dispatch a check dict to its grader. Unknown types raise KeyError."""
    kind = check["type"]
    if kind == "llm_judge":
        return llm_judge(check, answer, result, judge_llm, question)
    return _GRADERS[kind](check, answer, result)
