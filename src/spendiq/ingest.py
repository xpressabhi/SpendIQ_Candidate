"""Idempotent ingestion: CSVs -> SQLite, documents -> FTS5 chunk index.

Run with:  uv run python -m spendiq.ingest
"""

import csv
import re
import sys
from pathlib import Path

from pypdf import PdfReader

from .db import DB_PATH, connect, init_schema

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"

CSV_TABLES = [
    ("departments", "departments.csv"),
    ("vendors", "vendors.csv"),
    ("contracts", "contracts.csv"),
    ("purchase_orders", "purchase_orders.csv"),
    ("invoices", "invoices.csv"),
]

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120


def _clean(value: str) -> str | None:
    """Trim and convert empty strings to NULL (CSVs encode absence as '')."""
    value = value.strip()
    return value if value else None


def _bool(value: str | None) -> int | None:
    if value is None:
        return None
    return 1 if value.lower() in ("true", "1", "yes") else 0


def load_csv(conn, table: str, filename: str) -> None:
    rows = []
    with open(DATA_DIR / filename, newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            row = {k: _clean(v) for k, v in raw.items()}
            for key in ("preferred_status", "auto_renew"):
                if key in row:
                    row[key] = _bool(row[key])
            rows.append(row)
    if not rows:
        return
    cols = list(rows[0].keys())
    conn.executemany(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [[r.get(c) for c in cols] for r in rows],
    )
    print(f"  {table}: {len(rows)} rows")


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def extract_doc_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return extract_pdf_text(path)
    return path.read_text(encoding="utf-8")


def chunk_text(text: str, doc_id: str, source: str) -> list[dict]:
    """Split a document into heading-aware chunks of ~CHUNK_SIZE chars."""
    lines = text.splitlines()
    chunks, current_heading, buf = [], None, []
    buf_len = 0

    def flush():
        nonlocal buf, buf_len
        body = "\n".join(buf).strip()
        if body:
            chunks.append(
                {"doc_id": doc_id, "source_path": source,
                 "heading": current_heading, "chunk_index": len(chunks), "text": body}
            )
        buf, buf_len = [], 0

    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            if buf_len >= 300:  # section boundary with meaningful content
                flush()
            current_heading = m.group(2).strip()
            continue
        if not line.strip():
            if buf_len >= 400:
                flush()
            continue
        buf.append(line)
        buf_len += len(line) + 1
        if buf_len >= CHUNK_SIZE:
            flush()
    flush()

    # Guard: no headings found -> split long runs so chunks stay bounded.
    long = [c for c in chunks if len(c["text"]) > CHUNK_SIZE + CHUNK_OVERLAP * 4]
    for c in long:
        chunks.remove(c)
        start = 0
        while start < len(c["text"]):
            end = min(start + CHUNK_SIZE, len(c["text"]))
            chunks.append(
                {"doc_id": c["doc_id"], "source_path": c["source_path"],
                 "heading": c["heading"], "chunk_index": len(chunks),
                 "text": c["text"][start:end]}
            )
            if end == len(c["text"]):
                break
            start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def load_documents(conn) -> int:
    """Index contract documents (MD + PDF) and policy documents."""
    docs: list[tuple[str, str, Path]] = []

    # Policies: every .md in docs/policies.
    for path in sorted(DOCS_DIR.glob("policies/*.md")):
        docs.append((f"POL-{path.stem}", str(path.relative_to(ROOT)), path))

    # Contracts: follow document_path from contracts.csv. Skip .md redirect
    # stubs that point at a PDF in the same directory.
    for row in conn.execute("SELECT document_path FROM contracts WHERE document_path IS NOT NULL"):
        rel = row["document_path"]
        path = (ROOT / "docs" / rel).resolve()
        if not path.exists():
            print(f"  [warn] missing document for {rel}")
            continue
        if path.suffix == ".md":
            stub = path.read_text(encoding="utf-8")
            if "# (Redirect)" in stub:
                pdf = path.with_suffix(".pdf")
                if pdf.exists():
                    path = pdf
                else:
                    print(f"  [warn] redirect stub without PDF: {rel}")
                    continue
        docs.append((path.stem, str(path.relative_to(ROOT)), path))

    conn.execute("DELETE FROM doc_chunks")
    total = 0
    for doc_id, rel, path in docs:
        text = extract_doc_text(path)
        chunks = chunk_text(text, doc_id, rel)
        conn.executemany(
            "INSERT INTO doc_chunks (doc_id, source_path, heading, chunk_index, text) "
            "VALUES (:doc_id, :source_path, :heading, :chunk_index, :text)",
            chunks,
        )
        total += len(chunks)
        print(f"  {doc_id}: {len(chunks)} chunks ({path.name})")
    return total


def ingest() -> None:
    print(f"DB: {DB_PATH}")
    if DB_PATH.exists():
        DB_PATH.unlink()
        print("  dropped existing DB (fresh ingest)")
    conn = connect(DB_PATH)
    init_schema(conn)
    print("Loaded tables:")
    for table, filename in CSV_TABLES:
        load_csv(conn, table, filename)
    conn.commit()
    print("Documents:")
    n_chunks = load_documents(conn)
    conn.commit()
    print(f"Total document chunks: {n_chunks}")
    for view in ("v_invoice_terms_vs_contract", "v_contract_spend_vs_cap",
                 "v_split_purchase_orders", "v_duplicate_invoices"):
        count = conn.execute(f"SELECT COUNT(*) AS n FROM {view}").fetchone()["n"]
        print(f"  {view}: {count} flagged rows")
    conn.close()
    print("Ingest complete.")


if __name__ == "__main__":
    sys.exit(ingest())
