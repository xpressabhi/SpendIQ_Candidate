"""Document retrieval: FTS5 keyword search over chunked contract/policy docs."""

import re

from .db import connect

STOPWORDS = {"a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "with",
             "what", "which", "who", "how", "our", "we", "do", "is", "are", "any",
             "has", "have", "does", "about", "us", "their", "them", "it"}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(query: str) -> list[str]:
    """Lowercase, split on non-alphanumerics (incl. hyphens — FTS5 treats
    '-' as column-filter syntax, so 'auto-renewal' must become two tokens)."""
    return [t for t in _TOKEN_RE.findall(query.lower()) if t not in STOPWORDS and len(t) > 2]


def search_docs(query: str, doc_filter: str | None = None, k: int = 4) -> list[dict]:
    """Keyword search over doc chunks with an OR-term fallback.

    Returns chunks ordered by BM25 relevance with a snippet highlight.
    """
    conn = connect(read_only=True)
    try:
        terms = _tokens(query)
        if not terms:
            return []
        escaped = [f"{t}*" for t in terms]
        where = ""
        params: list = []
        if doc_filter:
            where = "AND (doc_id LIKE ? OR source_path LIKE ?)"
            params = [f"%{doc_filter}%", f"%{doc_filter}%"]
        for mode in ("AND", "OR"):
            match = f" {mode} ".join(escaped).strip()
            sql = (
                "SELECT doc_id, source_path, heading, text, "
                "bm25(doc_chunks_fts) AS score, "
                "snippet(doc_chunks_fts, 3, '…', '…', ' … ', 24) AS snip "
                f"FROM doc_chunks_fts WHERE doc_chunks_fts MATCH ? {where} "
                "ORDER BY score LIMIT ?"
            )
            rows = conn.execute(sql, [match, *params, k]).fetchall()
            if rows:
                return [dict(r) for r in rows]
        return []
    finally:
        conn.close()


def format_search_results(chunks: list[dict]) -> str:
    """Render retrieval results for the agent (document + clause citations)."""
    if not chunks:
        return "No matching document chunks found."
    out = []
    for c in chunks:
        heading = f" — {c['heading']}" if c.get("heading") else ""
        out.append(f"[{c['doc_id']}]{heading} ({c['source_path']})")
        out.append(c["text"][:900])
        out.append("")
    return "\n".join(out)
