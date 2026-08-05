"""Unit tests for retrieval, SQL safety, views, and utility tools (no LLM)."""

import sqlite3

import pytest

from spendiq.db import DB_PATH, connect
from spendiq.retrieval import search_docs
from spendiq.tools import (
    _validate_sql,
    calculate,
    date_utils,
    query_structured_data,
    resolve_entity,
)


@pytest.fixture(scope="module")
def db():
    if not DB_PATH.exists():
        pytest.skip("run `make ingest` first")
    return connect(DB_PATH, read_only=True)


def test_sql_rejects_writes():
    for sql in ("DELETE FROM vendors", "UPDATE invoices SET amount=0",
                "INSERT INTO vendors VALUES (1)", "DROP TABLE vendors"):
        with pytest.raises(ValueError):
            _validate_sql(sql)


def test_sql_accepts_reads():
    _validate_sql("SELECT * FROM vendors LIMIT 5")
    _validate_sql("WITH x AS (SELECT 1) SELECT * FROM x")


def test_sql_tool_counts():
    out = query_structured_data.invoke("SELECT COUNT(*) AS n FROM vendors")
    assert "n" in out and "200" in out


def test_terms_mismatch_view(db):
    n = db.execute("SELECT COUNT(*) FROM v_invoice_terms_vs_contract").fetchone()[0]
    assert n >= 1


def test_over_cap_view(db):
    n = db.execute("SELECT COUNT(*) FROM v_contract_spend_vs_cap").fetchone()[0]
    assert n >= 1


def test_split_po_view(db):
    n = db.execute("SELECT COUNT(*) FROM v_split_purchase_orders").fetchone()[0]
    assert n >= 1


def test_retrieval_policy_splitting():
    hits = search_docs("splitting purchase orders", k=4)
    assert any("POL-procurement_policy" in h["doc_id"] for h in hits)


def test_retrieval_pdf_contract():
    hits = search_docs("aperture notice renewal", k=4)
    assert any("CTR-0013" in h["doc_id"] for h in hits)


def test_retrieval_or_fallback():
    hits = search_docs("expense reimbursement approval", k=2)
    assert len(hits) > 0


def test_calculate_basic():
    assert calculate.invoke({"expression": "(15000 + 30000) * 1.2"}) == "54000"
    assert calculate.invoke({"expression": "494124.55 - 420000"}) == "74124.55"


def test_calculate_rejects_code():
    out = calculate.invoke({"expression": "__import__('os').system('ls')"})
    assert "Could not evaluate" in out
    assert "Could not evaluate" in calculate.invoke({"expression": "1; 2"})
    assert "division by zero" in calculate.invoke({"expression": "1 / 0"})


def test_date_utils_today():
    assert date_utils.invoke({"operation": "today"}) == "2026-04-21"


def test_date_utils_windows():
    assert date_utils.invoke({"operation": "add_days", "date1": "today", "n": 90}) == "2026-07-20"
    assert date_utils.invoke({"operation": "add_months", "date1": "today", "n": -12}) == "2025-04-21"
    assert date_utils.invoke({"operation": "start_of_year", "date1": "today"}) == "2026-01-01"
    assert date_utils.invoke(
        {"operation": "days_between", "date1": "2026-04-21", "date2": "2026-06-01"}
    ) == "41"


def test_date_utils_month_edges():
    assert date_utils.invoke({"operation": "end_of_month", "date1": "2026-02-15"}) == "2026-02-28"
    assert date_utils.invoke({"operation": "start_of_month", "date1": "2026-04-21"}) == "2026-04-01"
    assert date_utils.invoke({"operation": "end_of_year", "date1": "today"}) == "2026-12-31"
    assert date_utils.invoke({"operation": "add_months", "date1": "2026-01-31", "n": 1}) == "2026-02-28"


def test_date_utils_rejects_bad_input():
    assert "Unknown operation" in date_utils.invoke({"operation": "frobnicate"})
    assert "not a valid date" in date_utils.invoke(
        {"operation": "add_days", "date1": "not-a-date", "n": 1}
    )


def test_resolve_entity_fuzzy_name():
    out = resolve_entity.invoke({"query": "stratos"})
    assert "VEND-00001" in out
    assert "Stratos Cloud Services" in out


def test_resolve_entity_ambiguous_name():
    out = resolve_entity.invoke({"query": "orion"})
    assert "VEND-00003" in out
    assert "Orion Logistics Partners" in out


def test_resolve_entity_by_id():
    assert "CTR-0001" in resolve_entity.invoke({"query": "CTR-0001"})
    assert "No vendor, contract, or department matches" in resolve_entity.invoke(
        {"query": "zzz-no-such-entity"}
    )


def test_leverage_view(db):
    n = db.execute("SELECT COUNT(*) FROM v_vendor_leverage").fetchone()[0]
    assert n >= 1
