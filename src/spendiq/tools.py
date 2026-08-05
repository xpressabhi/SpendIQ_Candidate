"""The two agent tools: read-only SQL over structured data, and document
retrieval over contract/policy chunks. Both return citation-ready output."""

import json
import re
import sqlite3

from langchain_core.tools import tool

from .db import SCHEMA_SUMMARY, connect
from .retrieval import format_search_results, search_docs

_READ_ONLY_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
MAX_ROWS = 100
MAX_CELL = 120


def _validate_sql(sql: str) -> None:
    stripped = re.sub(r"--[^\n]*", "", sql)
    if ";" in stripped.rstrip().rstrip(";"):
        raise ValueError("Only a single read-only statement is allowed.")
    if not _READ_ONLY_RE.match(stripped):
        raise ValueError("Only SELECT / WITH queries are allowed.")
    lowered = stripped.lower()
    for banned in ("insert", "update", "delete", "drop", "alter", "create", "attach", "pragma"):
        if re.search(rf"\b{banned}\b", lowered):
            raise ValueError(f"Statement contains disallowed keyword: {banned}")


def _rows_to_text(columns: list[str], rows: list) -> str:
    lines = [", ".join(columns)]
    for row in rows[:MAX_ROWS]:
        lines.append(", ".join(
            str(c)[:MAX_CELL] if c is not None else "NULL" for c in row
        ))
    if len(rows) > MAX_ROWS:
        lines.append(f"... truncated to {MAX_ROWS} rows")
    return "\n".join(lines)


_SQL_TOOL_DESCRIPTION = """Run a read-only SQL query against the spend database and return the
results as text. Use this for any question about vendors, contracts,
purchase orders, invoices, amounts, dates, or spend totals.

Schema and helpful views:
{schema}
""".format(schema=SCHEMA_SUMMARY)


@tool(description=_SQL_TOOL_DESCRIPTION)
def query_structured_data(sql: str) -> str:
    """Execute a read-only SQL query; returns rows as text."""
    _validate_sql(sql)
    conn = connect(read_only=True)
    try:
        cur = conn.execute(sql)
        rows = cur.fetchmany(MAX_ROWS + 1)
        columns = [d[0] for d in cur.description] if cur.description else []
        if not columns:
            return "Query returned no columns."
        return _rows_to_text(columns, rows)
    except sqlite3.Error as exc:
        return f"SQL error: {exc}"
    finally:
        conn.close()


@tool
def retrieve_documents(query: str, doc_filter: str = "", k: int = 4) -> str:
    """Search the contract and policy documents (chunked by section) and
    return the most relevant passages with their document IDs.

    Use this for questions about contract clauses, terms, notice periods,
    auto-renewal language, or company policies (approval thresholds,
    PO splitting, payment terms, vendor risk).

    Args:
        query: the search phrase, e.g. 'notice period', 'PO splitting'.
        doc_filter: optional partial match on document ID or path to limit
            the search to one document, e.g. 'CTR-0002' or 'procurement'.
        k: number of passages to return (1-6).
    """
    chunks = search_docs(query, doc_filter or None, k=min(max(k, 1), 6))
    return format_search_results(chunks)


def build_tools():
    return [query_structured_data, retrieve_documents]


def summarize_sql_result(result_text: str) -> dict:
    """Extract key columns/rows from a SQL tool result for UI display."""
    try:
        lines = [l for l in result_text.splitlines() if l.strip()]
        if not lines:
            return {}
        cols = lines[0].split(", ")
        rows = []
        for l in lines[1:]:
            if l.startswith("... truncated"):
                break
            vals = l.split(", ")
            rows.append({c: v for c, v in zip(cols, vals)})
        return {"columns": cols, "rows": rows[:5]}
    except Exception:
        return {}
