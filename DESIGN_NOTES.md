# SpendIQ Copilot — Design Notes

## Architecture

```
data/*.csv ──┐
             ├─► spendiq.ingest ──► data/spendiq.db
docs/*.md,   │                        ├─ normalized tables (5)
docs/*.pdf ──┘                        ├─ 7 analytic SQL views
                                      └─ FTS5 keyword index (80 chunks)
                          ┌───────────┴────────────┐
                          │  LangGraph agent        │
                          │  2 core + 3 utility tools │
                          └───────────┬────────────┘
                             FastAPI /api/chat ──► static chat UI
```

Modules under `src/spendiq/`:

- `ingest.py` — idempotent ingestion (`uv run python -m spendiq.ingest`), drops and
  rebuilds `data/spendiq.db` from the 5 CSVs + 18 documents.
- `db.py` — schema, 6 analytic views, FTS5 virtual table, read-only connection helper.
- `retrieval.py` — tokenization + BM25 search with AND→OR fallback and doc filter.
- `tools.py` — the two LangChain tools (SQL + retrieval).
- `agent.py` — LangGraph `create_react_agent` loop, system prompt, tool-call/source trace.
- `api.py` — FastAPI app (`/api/chat`, static UI at `/`).
- `static/index.html` — single-page chat UI with tool/source chips.

## Key decisions

### Data modeling
- **SQLite instead of Postgres/pgvector.** No Docker/Postgres on the dev machine;
  SQLite + FTS5 is zero-setup and the demo runs anywhere. The schema is plain DDL and
  would port to Postgres with trivial changes (bools, dates, views).
- **Anomalies as SQL views, not agent tools.** The agent needs only two tools
  (SQL + retrieval); the dataset's anomalies (terms mismatches, over-cap contracts,
  split POs, duplicates, renegotiation leverage) are encoded as seven read-only views. This keeps the agent
  small and makes anomaly questions a one-line query while staying within the tool
  budget — the "analytics" are a data-modeling concern, not agent complexity.
- **Empty-string FKs normalized to NULL** (CSVs encode absence as `''`).
- **Reference date is baked into the views** (`2026-04-21`), so "next 90 days" style
  filters are deterministic; agents also get it in the system prompt.
- FX: invoices/POs are all USD; contracts carry EUR/GBP. Not auto-converted (no rate
  table in the data); noted as a limitation.

### Chunking / retrieval
- **Documents chunked by Markdown headings** (~900 chars with heading context);
  PDFs (3 of them) extracted with pypdf, the 3 markdown "redirect stubs" skipped in
  favor of their PDFs.
- **FTS5 with porter + unicode61 tokenizer** and prefix wildcards; AND query first,
  OR-term fallback when the AND match is empty. Chosen over embeddings because the
  corpus is tiny (~80 chunks): keyword BM25 is deterministic, offline, and needs no
  model download — critical for a live demo. An embeddings/vector path would be the
  upgrade if the corpus grew (hybrid retrieval).
- Found and fixed two FTS5 gotchas during development: hyphenated tokens
  (`auto-renewal` parses as column-filter syntax) and `snippet()` column indices.

### Agent design
- **LangGraph `create_react_agent`** with five tools:
  - `query_structured_data` (read-only SQL — validated as single SELECT/WITH, executed against a `mode=ro` connection) and `retrieve_documents` (FTS5 with optional doc filter) are the two core tools.
  - `calculate` — safe arithmetic via an AST whitelist (no `eval`), so the agent never approximates math itself.
  - `date_utils` — date arithmetic anchored to the reference date (add days/months, days-between, month/year bounds); converts "next 90 days"-style phrases into exact ISO dates for SQL.
  - `resolve_entity` — fuzzy name/ID lookup across vendors, contracts, and departments returning canonical IDs (VEND-…, CTR-…, DEPT-…) so SQL runs against exact keys instead of guesses.
- **System prompt** enforces: citations in every answer (INV-/PO-/CTR-/VEND- IDs,
  document + section for clauses), explicit "I don't know" instead of hallucinated
  numbers, clarifying-question-or-assumption on ambiguous input, and scope
  restriction on referential follow-ups ("those/the above").
- **Conversation memory** via LangGraph `InMemorySaver` checkpointer keyed by
  thread_id; the graph is a module singleton so memory survives across requests.
- **Trace for the UI** walks the final message history: every AI tool call becomes a
  chip; document IDs extracted from retrieval results become source chips.
- LangServe and LangSmith deliberately not used: FastAPI wraps the compiled graph
  directly (fewer deps, one API surface), and LangSmith needs its own account.

### LLM
- **OpenCode Zen free endpoint** (`https://opencode.ai/zen/v1`, api key `public`,
  model `deepseek-v4-flash-free`) — OpenAI-compatible, $0, no signup. Verified
  tool-calling works before building the agent. Provider is abstracted behind three
  env vars, so any OpenAI-compatible endpoint (or paid key) can be swapped in.

## What was verified

- `make test` — 9 unit tests (SQL safety, views, retrieval, PDF contract hits).
- `make validate` — 14 representative questions across all 4 tiers, incl. every
  known anomaly (4 terms mismatches INV-001560-63, 11 over-cap contracts
  CTR-0002/0008/0014, split-PO clusters, duplicates, 90-day expiry list with
  notice-window deadlines against 2026-04-21) and the Tier 4 stretch cases
  (renegotiation-leverage brief, duplicate-invoice surface).
- Browser demo: chat round-trip with tool chips and citations rendered.
- Follow-up ("and which of those auto-renew?") correctly scoped to the prior turn.

## Limitations

- **SQLite not Postgres/pgvector** — fine at this scale; no full hybrid retrieval.
- **In-memory checkpointer** — conversation memory is lost on server restart; a
  durable store (SQLite checkpointer) would fix it.
- **No auth / single user / no rate limiting** — POC only.
- **FX normalization absent** — aggregate spend is USD-only.
- **View heuristics are intentionally narrow** (e.g. split-PO = same vendor +
  department + day, each <$10K, sum ≥$10K); they catch the known cases, not every
  real-world variant.
- **Free LLM endpoint** — rate limits/availability are outside our control; the
  `SPENDIQ_MOCK=1` flag keeps the UI demo-able offline.

## With more time

1. Hybrid retrieval: embeddings (OpenAI/Anthropic via the same key) + FTS5 fusion,
   with a proper eval set of ~50 Q/A pairs to compare recall.
2. Durable checkpointer + per-user sessions; streaming responses (LangGraph
   streaming is already wired, the UI would just consume it).
3. Better anomaly detection: ML-ish heuristics (vendor name fuzzy matching for
   duplicates, regression on historical spend vs cap trends).
4. Guardrails: SQL tool with a denylist + query cost caps; eval harness in CI.
5. Postgres + pgvector deployment with read replicas for the SQL tool at 10x scale.
