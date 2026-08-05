"""Unit tests for retrieval, SQL safety, and view correctness (no LLM)."""

import sqlite3

import pytest

from spendiq.db import DB_PATH, connect
from spendiq.retrieval import search_docs
from spendiq.tools import _validate_sql, query_structured_data


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
