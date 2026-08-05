"""SQLite schema, analytic views, and connection helpers."""

import sqlite3
from pathlib import Path

REFERENCE_DATE = "2026-04-21"
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "spendiq.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS departments (
    department_id    TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    cost_center_code TEXT,
    vp_name          TEXT
);

CREATE TABLE IF NOT EXISTS vendors (
    vendor_id             TEXT PRIMARY KEY,
    vendor_name           TEXT NOT NULL,
    tax_id                TEXT,
    country               TEXT,
    category              TEXT,
    onboarded_date        TEXT,
    preferred_status      INTEGER,
    risk_rating           TEXT,
    payment_terms_default INTEGER,
    status                TEXT
);

CREATE TABLE IF NOT EXISTS contracts (
    contract_id         TEXT PRIMARY KEY,
    vendor_id           TEXT REFERENCES vendors(vendor_id),
    contract_name       TEXT,
    contract_type       TEXT,
    start_date          TEXT,
    end_date            TEXT,
    auto_renew          INTEGER,
    notice_period_days  INTEGER,
    total_value_cap_usd NUMERIC,
    currency            TEXT,
    payment_terms_days  INTEGER,
    status              TEXT,
    document_path       TEXT
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id           TEXT PRIMARY KEY,
    vendor_id       TEXT REFERENCES vendors(vendor_id),
    contract_id     TEXT REFERENCES contracts(contract_id),
    department_id   TEXT REFERENCES departments(department_id),
    po_date         TEXT,
    line_description TEXT,
    total_amount    NUMERIC,
    currency        TEXT,
    status          TEXT,
    requestor_name  TEXT,
    approval_level  TEXT
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id        TEXT PRIMARY KEY,
    po_id             TEXT REFERENCES purchase_orders(po_id),
    vendor_id         TEXT REFERENCES vendors(vendor_id),
    invoice_date      TEXT,
    due_date          TEXT,
    amount            NUMERIC,
    currency          TEXT,
    status            TEXT,
    payment_terms_days INTEGER,
    paid_date         TEXT
);
"""

VIEWS_SQL = f"""
-- Invoices billed with shorter payment terms than the underlying contract states.
CREATE VIEW IF NOT EXISTS v_invoice_terms_vs_contract AS
SELECT
    i.invoice_id,
    i.vendor_id,
    v.vendor_name,
    i.po_id,
    c.contract_id,
    c.contract_name,
    i.payment_terms_days  AS invoice_terms_days,
    c.payment_terms_days  AS contract_terms_days,
    i.invoice_date,
    i.amount,
    i.status
FROM invoices i
JOIN purchase_orders p ON p.po_id = i.po_id
JOIN contracts c ON c.contract_id = p.contract_id
JOIN vendors v ON v.vendor_id = i.vendor_id
WHERE i.payment_terms_days IS NOT NULL
  AND c.payment_terms_days IS NOT NULL
  AND i.payment_terms_days < c.payment_terms_days;

-- Cumulative invoice spend per contract vs the stated total value cap.
CREATE VIEW IF NOT EXISTS v_contract_spend_vs_cap AS
SELECT
    c.contract_id,
    c.contract_name,
    c.vendor_id,
    v.vendor_name,
    c.total_value_cap_usd,
    ROUND(SUM(i.amount), 2) AS invoice_spend,
    ROUND(SUM(i.amount) - c.total_value_cap_usd, 2) AS over_cap_by
FROM contracts c
JOIN vendors v ON v.vendor_id = c.vendor_id
LEFT JOIN purchase_orders p ON p.contract_id = c.contract_id
LEFT JOIN invoices i ON i.po_id = p.po_id
WHERE c.total_value_cap_usd IS NOT NULL
GROUP BY c.contract_id
HAVING invoice_spend > c.total_value_cap_usd;

-- PO clusters per vendor+department+day where each PO is under $10K but the
-- combined value crosses it (splitting to dodge the approval threshold).
CREATE VIEW IF NOT EXISTS v_split_purchase_orders AS
SELECT
    po.vendor_id,
    v.vendor_name,
    po.department_id,
    d.name AS department_name,
    po.po_date,
    COUNT(*)                                  AS po_count,
    ROUND(SUM(po.total_amount), 2)            AS combined_amount,
    GROUP_CONCAT(po.po_id)                    AS po_ids,
    GROUP_CONCAT(po.line_description)         AS descriptions,
    GROUP_CONCAT(po.requestor_name)           AS requestors
FROM purchase_orders po
JOIN vendors v ON v.vendor_id = po.vendor_id
JOIN departments d ON d.department_id = po.department_id
WHERE po.total_amount < 10000
  AND po.status != 'Cancelled'
GROUP BY po.vendor_id, po.department_id, po.po_date
HAVING COUNT(*) >= 2 AND combined_amount >= 10000;

-- Contract expiry dashboard anchored to the reference date.
CREATE VIEW IF NOT EXISTS v_contract_expiry AS
SELECT
    c.contract_id,
    c.contract_name,
    c.vendor_id,
    v.vendor_name,
    c.contract_type,
    c.status,
    c.start_date,
    c.end_date,
    c.auto_renew,
    c.notice_period_days,
    c.currency,
    ROUND(julianday(c.end_date) - julianday('{REFERENCE_DATE}'), 0) AS days_to_expiry
FROM contracts c
JOIN vendors v ON v.vendor_id = c.vendor_id
WHERE c.end_date >= '{REFERENCE_DATE}';

-- Vendors with spend and no active contract.
CREATE VIEW IF NOT EXISTS v_vendor_spend_no_active_contract AS
SELECT
    i.vendor_id,
    v.vendor_name,
    v.status AS vendor_status,
    ROUND(SUM(i.amount), 2) AS total_invoice_spend,
    COUNT(*)                AS invoice_count
FROM invoices i
JOIN vendors v ON v.vendor_id = i.vendor_id
WHERE v.status = 'Active'
  AND i.status != 'Disputed'
  AND NOT EXISTS (
      SELECT 1 FROM contracts c
      WHERE c.vendor_id = i.vendor_id AND c.status = 'Active'
  )
GROUP BY i.vendor_id;

-- Same-vendor invoices with identical amounts in the last six months.
CREATE VIEW IF NOT EXISTS v_duplicate_invoices AS
SELECT
    a.vendor_id,
    v.vendor_name,
    a.amount,
    a.invoice_id AS invoice_id_a,
    a.invoice_date AS date_a,
    b.invoice_id AS invoice_id_b,
    b.invoice_date AS date_b,
    ROUND(julianday(b.invoice_date) - julianday(a.invoice_date), 0) AS days_between
FROM invoices a
JOIN invoices b ON b.vendor_id = a.vendor_id AND b.amount = a.amount AND b.invoice_id > a.invoice_id
JOIN vendors v ON v.vendor_id = a.vendor_id
WHERE a.invoice_date >= '{REFERENCE_DATE}' - 180
  AND b.invoice_date >= a.invoice_date
  AND b.invoice_date <= date(a.invoice_date, '+180 days');
"""

DOC_CHUNKS_SQL = """
CREATE TABLE IF NOT EXISTS doc_chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      TEXT NOT NULL,
    source_path TEXT NOT NULL,
    heading     TEXT,
    chunk_index INTEGER,
    text        TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS doc_chunks_fts USING fts5(
    doc_id UNINDEXED, source_path UNINDEXED, heading UNINDEXED, text,
    content='doc_chunks', content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS doc_chunks_ai AFTER INSERT ON doc_chunks BEGIN
    INSERT INTO doc_chunks_fts(rowid, doc_id, source_path, heading, text)
    VALUES (new.id, new.doc_id, new.source_path, new.heading, new.text);
END;

CREATE TRIGGER IF NOT EXISTS doc_chunks_ad AFTER DELETE ON doc_chunks BEGIN
    INSERT INTO doc_chunks_fts(doc_chunks_fts, rowid, doc_id, source_path, heading, text)
    VALUES ('delete', old.id, old.doc_id, old.source_path, old.heading, old.text);
END;

CREATE TRIGGER IF NOT EXISTS doc_chunks_au AFTER UPDATE ON doc_chunks BEGIN
    INSERT INTO doc_chunks_fts(doc_chunks_fts, rowid, doc_id, source_path, heading, text)
    VALUES ('delete', old.id, old.doc_id, old.source_path, old.heading, old.text);
    INSERT INTO doc_chunks_fts(rowid, doc_id, source_path, heading, text)
    VALUES (new.id, new.doc_id, new.source_path, new.heading, new.text);
END;
"""

SCHEMA_SUMMARY = """
Tables:
- departments(department_id, name, cost_center_code, vp_name)
- vendors(vendor_id, vendor_name, tax_id, country, category, onboarded_date, preferred_status, risk_rating, payment_terms_default, status)
- contracts(contract_id, vendor_id, contract_name, contract_type, start_date, end_date, auto_renew, notice_period_days, total_value_cap_usd, currency, payment_terms_days, status, document_path)
- purchase_orders(po_id, vendor_id, contract_id, department_id, po_date, line_description, total_amount, currency, status, requestor_name, approval_level)
- invoices(invoice_id, po_id, vendor_id, invoice_date, due_date, amount, currency, status, payment_terms_days, paid_date)

Convenience views (prefer these when they match the question):
- v_invoice_terms_vs_contract: invoices billed with shorter payment terms than their contract states
- v_contract_spend_vs_cap: contracts where cumulative invoice spend exceeds total_value_cap_usd
- v_split_purchase_orders: same vendor+department+day PO clusters, each under $10K but combined >= $10K (policy forbids splitting to avoid approval)
- v_contract_expiry: active contracts with days_to_expiry, auto_renew, notice_period_days
- v_vendor_spend_no_active_contract: vendors with spend but no active contract
- v_duplicate_invoices: same vendor + same amount, recent duplicates

Notes:
- Reference date (today) is {REFERENCE_DATE}. Use it for 'YTD', 'last 12 months', 'next 90 days' filters.
- Invoices and POs are all USD. Contracts may be EUR/GBP — check currency before mixing.
- invoice.amount is the unit of spend. Purchase order totals are commitments.
"""


def connect(db_path: Path | str = DB_PATH, read_only: bool = False) -> sqlite3.Connection:
    """Open a connection. read_only=True opens via URI mode=ro (query safety)."""
    if read_only:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables, FTS index, and analytic views."""
    conn.executescript(SCHEMA_SQL)
    conn.executescript(VIEWS_SQL)
    conn.executescript(DOC_CHUNKS_SQL)
    conn.commit()
