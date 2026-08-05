"""Agent tools: read-only SQL over structured data, document retrieval over
contract/policy chunks, safe arithmetic, date utilities, and entity
lookup. All return citation-ready output."""

import ast
import datetime as dt
import json
import re
import sqlite3

from langchain_core.tools import tool

from .db import REFERENCE_DATE, SCHEMA_SUMMARY, connect
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


_MAX_DEPTH = 4
_ALLOWED_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}


def _eval_math(node: ast.AST, depth: int = 0):
    if depth > _MAX_DEPTH:
        raise ValueError("expression too complex")
    if isinstance(node, ast.Expression):
        return _eval_math(node.body, depth + 1)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        val = _eval_math(node.operand, depth + 1)
        return val if isinstance(node.op, ast.UAdd) else -val
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        lhs = _eval_math(node.left, depth + 1)
        rhs = _eval_math(node.right, depth + 1)
        try:
            return _ALLOWED_BINOPS[type(node.op)](lhs, rhs)
        except ZeroDivisionError:
            raise ValueError("division by zero") from None
    raise ValueError("only arithmetic expressions are allowed")


@tool
def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression exactly (no approximation).

    Use this whenever the answer requires arithmetic beyond a plain SUM:
    percentages, averages, ratios, markups, tax, compounding, or
    comparing two spend figures. The model is prone to arithmetic errors,
    so prefer this tool over doing math yourself.

    Args:
        expression: arithmetic using + - * / // % ** and parentheses,
            e.g. '494124.55 - 420000', '(152000 * 1.08) / 12'.

    Returns:
        The numeric result, e.g. '74124.55'.
    """
    try:
        tree = ast.parse(expression, mode="eval")
        value = _eval_math(tree)
    except (ValueError, SyntaxError, TypeError, OverflowError) as exc:
        return f"Could not evaluate: {exc}"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value:.4f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def _parse_date(text: str) -> dt.date:
    if text in ("today", "now", "reference"):
        return dt.date.fromisoformat(REFERENCE_DATE)
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise ValueError(
            f"'{text}' is not a valid date (YYYY-MM-DD) or the reference date 'today'"
        ) from None


def _add_months(d: dt.date, months: int) -> dt.date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return dt.date(year, month, day)


_DATE_OPS = {
    "today",
    "add_days", "add_months", "days_between",
    "start_of_month", "end_of_month", "start_of_year", "end_of_year",
}


_DATE_UTILS_DESCRIPTION = f"""Date arithmetic for date-window questions.

The spend database's reference date is {REFERENCE_DATE}. Use this
tool to translate phrases like 'next 90 days', 'last 12 months',
'last six months', or 'YTD' into exact ISO dates (YYYY-MM-DD) before
writing SQL filters.

Args:
    operation: one of
        - 'today': returns the reference date
        - 'add_days': date1 + n days
        - 'add_months': date1 + n months
        - 'days_between': days between date1 and date2 (signed)
        - 'start_of_month' / 'end_of_month' / 'start_of_year' /
          'end_of_year': truncate/extend date1
    date1, date2: 'today' or an ISO date (YYYY-MM-DD)
    n: number of days/months to add (can be negative)

Returns:
    An ISO date or an integer (for 'days_between').

Examples:
    operation='add_days', date1='today', n=90 -> '2026-07-20'
    operation='add_months', date1='today', n=-12 -> '2025-04-21'
    operation='days_between', date1='2026-04-21', date2='2026-06-01' -> 41
"""


@tool(description=_DATE_UTILS_DESCRIPTION)
def date_utils(operation: str, date1: str = "", date2: str = "", n: int = 0) -> str:
    """Date arithmetic for date-window questions relative to the reference date."""
    try:
        if operation not in _DATE_OPS:
            return f"Unknown operation '{operation}'. Valid: {', '.join(sorted(_DATE_OPS))}"
        d1 = _parse_date(date1) if operation != "today" else dt.date.fromisoformat(REFERENCE_DATE)
        if operation == "today":
            return d1.isoformat()
        if operation == "add_days":
            return (d1 + dt.timedelta(days=n)).isoformat()
        if operation == "add_months":
            return _add_months(d1, n).isoformat()
        if operation == "days_between":
            return str((_parse_date(date2) - d1).days)
        if operation == "start_of_month":
            return d1.replace(day=1).isoformat()
        if operation == "end_of_month":
            return ((d1.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
                    - dt.timedelta(days=1)).isoformat()
        if operation == "start_of_year":
            return d1.replace(month=1, day=1).isoformat()
        if operation == "end_of_year":
            return d1.replace(month=12, day=31).isoformat()
    except ValueError as exc:
        return f"Could not compute date: {exc}"
    return "Could not compute date."


_ENTITY_TABLES = {
    "vendors": ("vendor_id", "vendor_name"),
    "contracts": ("contract_id", "contract_name"),
    "departments": ("department_id", "name"),
}
_ENTITY_ID_RE = re.compile(r"^(VEND-\d{5}|CTR-\d{4}|DEPT-\d{3}|PO-\d{5}|INV-\d{6})$")


@tool
def resolve_entity(query: str, k: int = 5) -> str:
    """Resolve a fuzzy name or ID fragment to canonical entity IDs.

    Use this when a question names a vendor, contract, or department and
    you need its exact ID (VEND-…, CTR-…, DEPT-…) for a SQL query — e.g.
    'Stratos Cloud' or 'the Orion logistics contract'. Returns canonical
    IDs plus a few identifying columns; then run your SQL against the
    returned IDs.

    Args:
        query: name fragment or ID, e.g. 'orion', 'CTR-001', 'strat'.
        k: max matches to return (1-10).

    Returns:
        Lines of the form: ID | name | extra context, or a no-match note.
    """
    k = min(max(k, 1), 10)
    conn = connect(read_only=True)
    try:
        if _ENTITY_ID_RE.match(query.strip()):
            rows = _by_id(conn, query.strip())
        else:
            rows = _by_name(conn, query.strip(), k)
        if not rows:
            return f"No vendor, contract, or department matches '{query}'."
        return "\n".join(f"{r[0]} | {r[1]} | {r[2]}" for r in rows[:k])
    except sqlite3.Error as exc:
        return f"Lookup error: {exc}"
    finally:
        conn.close()


def _by_id(conn: sqlite3.Connection, entity_id: str) -> list[tuple]:
    for table, (id_col, name_col) in _ENTITY_TABLES.items():
        row = conn.execute(
            f"SELECT {id_col}, {name_col}, 'exact id' FROM {table} WHERE {id_col} = ?",
            (entity_id,),
        ).fetchone()
        if row:
            return [tuple(row)]
    return []


def _by_name(conn: sqlite3.Connection, term: str, k: int) -> list[tuple]:
    like = f"%{term}%"
    out = []
    for table, (id_col, name_col) in _ENTITY_TABLES.items():
        if table == "contracts":
            rows = conn.execute(
                f"""SELECT c.{id_col}, c.{name_col}, 'vendor=' || v.vendor_name
                    FROM contracts c JOIN vendors v ON v.vendor_id = c.vendor_id
                    WHERE c.{name_col} LIKE ? OR v.vendor_name LIKE ?
                    ORDER BY c.{id_col} LIMIT ?""",
                (like, like, k),
            ).fetchall()
        elif table == "vendors":
            rows = conn.execute(
                f"SELECT {id_col}, {name_col}, category FROM vendors "
                f"WHERE {name_col} LIKE ? ORDER BY {id_col} LIMIT ?",
                (like, k),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {id_col}, {name_col}, vp_name FROM departments "
                f"WHERE {name_col} LIKE ? ORDER BY {id_col} LIMIT ?",
                (like, k),
            ).fetchall()
        out.extend(tuple(r) for r in rows)
    return out


def build_tools():
    return [query_structured_data, retrieve_documents, calculate, date_utils, resolve_entity]


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
