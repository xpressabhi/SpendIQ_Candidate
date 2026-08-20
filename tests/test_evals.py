"""Unit tests for eval graders and case definitions (no LLM required)."""

import re

import pytest

from spendiq.evals import graders
from spendiq.evals.cases import CASES, count_near


def res(answer: str = "", tools: list | None = None, sources: list | None = None):
    return {"answer": answer, "tools": tools or [], "sources": sources or []}


class TestContains:
    def test_contains_all_passes(self):
        ok, _ = graders.contains_all(
            {"values": ["882,050", "usd"]}, "Total spend was USD 882,050.", res()
        )
        assert ok is True

    def test_contains_all_fails_and_names_missing(self):
        ok, detail = graders.contains_all(
            {"values": ["882,050", "nimbus"]}, "Total spend was USD 882,050.", res()
        )
        assert ok is False
        assert "nimbus" in detail

    def test_contains_any(self):
        ok, _ = graders.contains_any(
            {"values": ["jan", "march", "april"]}, "Expires April 24, 2026.", res()
        )
        assert ok is True

    def test_contains_none_flags_forbidden(self):
        ok, detail = graders.contains_none(
            {"values": ["i don't know"]}, "I don't know the answer.", res()
        )
        assert ok is False
        assert "forbidden" in detail


class TestCountNear:
    def test_number_then_keyword(self):
        ok, _ = graders.regex_check(
            count_near("12", "contract"), "12 contracts auto-renew in 90 days.", res()
        )
        assert ok is True

    def test_spelled_out_number(self):
        ok, _ = graders.regex_check(
            count_near("9", "contract"), "Nine contracts auto-renew in 90 days.", res()
        )
        assert ok is True

    def test_spelled_out_hyphenated(self):
        ok, _ = graders.regex_check(
            count_near("47", "contract"), "Forty-seven contracts are active.", res()
        )
        assert ok is True

    def test_keyword_then_number(self):
        ok, _ = graders.regex_check(
            count_near("12", "contract"), "Expiring contracts: 12 total.", res()
        )
        assert ok is True

    def test_hyphenated_day_window(self):
        ok, _ = graders.regex_check(
            count_near("90", "day"), "A 90-day notice window applies.", res()
        )
        assert ok is True

    def test_no_false_positive_on_190(self):
        ok, _ = graders.regex_check(
            count_near("90", "day"), "The contract has a 190-day term.", res()
        )
        assert ok is False

    def test_keyword_missing(self):
        ok, _ = graders.regex_check(
            count_near("5", "purchase order"), "5 invoices were flagged.", res()
        )
        assert ok is False

    def test_patterns_compile(self):
        for pattern in (
            count_near("47", "contract"),
            count_near("4", "invoice"),
            count_near("125", "vendor"),
            count_near("90", "day"),
            count_near("10", "invoice"),
        ):
            re.compile(pattern["pattern"])


class TestToolAndSource:
    def test_tool_used(self):
        ok, _ = graders.tool_used(
            {"value": "query_structured_data"}, "", res(tools=[{"name": "query_structured_data"}])
        )
        assert ok is True

    def test_tool_not_used(self):
        ok, detail = graders.tool_used(
            {"value": "retrieve_documents"}, "", res(tools=[{"name": "calculate"}])
        )
        assert ok is False
        assert "calculate" in detail

    def test_source_cited(self):
        ok, _ = graders.source_cited(
            {"value": "CTR-0003"}, "", res(sources=["CTR-0003_orion_logistics_msa"])
        )
        assert ok is True


class TestJudgeParse:
    def test_plain_json(self):
        ok, reason = graders._parse_judge('{"pass": true, "reason": "correct"}')
        assert ok is True
        assert reason == "correct"

    def test_fenced_json(self):
        text = 'Here you go:\n```json\n{"pass": false, "reason": "wrong vendor"}\n```'
        ok, reason = graders._parse_judge(text)
        assert ok is False
        assert reason == "wrong vendor"

    def test_waffle_with_json(self):
        text = 'My verdict is {"pass": true, "reason": "mentions Redwood"} as shown.'
        ok, reason = graders._parse_judge(text)
        assert ok is True
        assert reason == "mentions Redwood"


class TestRunnerAggregation:
    def _make_run(self, ok_flags, status="ok"):
        return {
            "status": status, "elapsed_s": 1.0,
            "checks": [{"ok": f} for f in ok_flags],
            "answer": "x", "tools": [], "sources": [],
        }

    def test_majority_vote_passes(self):
        from spendiq.evals.cases import CASES
        case = CASES[0]
        runs = [self._make_run([True]), self._make_run([True]), self._make_run([False])]
        row = run_evals_helpers_aggregate(case, runs, pass_rate=0.5)
        assert row["status"] == "ok"
        assert row["checks"][0]["ok"] is True
        assert row["checks"][0]["runs_passed"] == 2
        assert row["checks"][0]["runs_total"] == 3

    def test_majority_vote_fails(self):
        from spendiq.evals.cases import CASES
        case = CASES[0]
        runs = [self._make_run([False]), self._make_run([True]), self._make_run([False])]
        row = run_evals_helpers_aggregate(case, runs, pass_rate=0.5)
        assert row["checks"][0]["ok"] is False

    def test_any_agent_crash_marks_error(self):
        from spendiq.evals.cases import CASES
        case = CASES[0]
        runs = [self._make_run([True]), self._make_run([], status="error")]
        row = run_evals_helpers_aggregate(case, runs, pass_rate=0.5)
        assert row["status"] == "error"


def run_evals_helpers_aggregate(case, runs, pass_rate):
    from spendiq.evals.runner import _aggregate
    return _aggregate(case, runs, pass_rate)


class TestCaseDefinitions:
    KNOWN_TYPES = {
        "contains_all", "contains_any", "contains_none", "regex",
        "tool_used", "source_cited", "llm_judge",
    }

    def test_unique_ids_and_tiers(self):
        ids = [c.id for c in CASES]
        assert len(ids) == len(set(ids))
        assert {c.tier for c in CASES} <= {"T1", "T2", "T3", "T4"}

    def test_all_tiers_covered(self):
        assert {c.tier for c in CASES} == {"T1", "T2", "T3", "T4"}

    def test_every_case_has_checks(self):
        assert all(c.checks for c in CASES)

    def test_check_types_known(self):
        for case in CASES:
            for check in case.checks:
                assert check["type"] in self.KNOWN_TYPES, case.id

    def test_judge_checks_have_rubric(self):
        for case in CASES:
            for check in case.checks:
                if check["type"] == "llm_judge":
                    assert check["rubric"].strip(), case.id
