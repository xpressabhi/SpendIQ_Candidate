# SpendIQ — Implementation Plan

## 1. Repo analysis

**What it is:** A 2-hour take-home for an AI & Data Engineer role — build a conversational "spend copilot" for a fictional retailer (Nimbus Retail Co.). Structured data (5 CSVs: 20 departments, 200 vendors, 80 contracts, ~1,970 POs, ~1,610 invoices) plus 18 documents (15 contracts — 12 MD + 3 PDF — and 3 policies). Reference "today" = **2026-04-21**. Key grading axes: agentic design, data modeling, code quality, demo-ability, production thinking.

### Planted edge cases (verified in the data)

- 4 invoices billed with payment terms shorter than their contract's stated terms
- 11 contracts where cumulative invoice spend exceeds the value cap (e.g. CTR-0002: $494K vs $420K cap)
- ~128 vendors with >$50K YTD spend and no active contract
- 12 contracts expiring within 90 days of the reference date
- PO-splitting to stay under the $10K approval threshold is prohibited per policy
- 3 PDFs (CTR-0001, 0003, 0013) whose MD stubs contain no terms — must extract from PDF
- Minor FX: contracts denominated in EUR/GBP; invoices/POs all USD

### Environment constraints

- No Docker, no Postgres → SQLite is the pragmatic DB choice (schema kept Postgres-portable) to avoid a setup rabbit hole during the live demo
- System `python3` is 3.9.6 (too old for current FastAPI/pydantic/sentence-transformers) → pin **Python 3.12 via `uv`** (`uv python pin 3.12`); `uv` already available
- `make` and `node`/`npm` (v24) available → `make ingest && make run` works
- Verified: the 3 PDFs are text-based 2-pagers and **pypdf extracts them cleanly** (validated on all three) — no OCR/layout library needed

## 2. Requirements → design mapping (brief §2, §6, §8)

| Brief requirement | Design |
| ----------------- | ------ |
| Ingests CSVs into a DB (reproducible, reruns from scratch) | `python -m spendiq.ingest`; idempotent drop/recreate; `make ingest` |
| Ingests documents into a retrieval store (MD + PDF) | pypdf + markdown readers; section-chunked into a keyword index (embeddings optional) |
| Answers NL questions over structured, docs, or both | LangGraph tool-calling agent, 2 tools (below) |
| Explains itself: tools + sources, citations (invoice IDs, clauses, docs) | System prompt mandates citations; UI shows tool calls + sources |
| Runs end-to-end from a simple chat UI | FastAPI + single-page chat (input, conversation, source panel) |
| At least two tools: SQL + document retrieval | Exactly two tools: `query_structured_data`, `retrieve_documents` |
| README with clean-clone run instructions + `.env.example` | README (`uv sync && make ingest && make run`), `.env.example` committed |
| DESIGN_NOTES.md: architecture, data modeling, chunking/embeddings, tool exposure, limitations, more-time | Single doc covering all six listed topics |

## 3. Stack

- **Backend:** Python 3.12, FastAPI, managed with `uv` (`uv` project, pinned interpreter)
- **DB:** SQLite (Postgres-portable schema)
- **Docs:** pypdf for PDF extraction (validated); chunking by section/clause (~300–500 tokens, overlap)
- **Retrieval:** hybrid — lightweight keyword scoring (primary, zero dependencies, works offline) + optional vector cosine via sentence-transformers/OpenAI embeddings as a fallback path. Only ~18 short docs ≈ 100–150 chunks, so keyword-first retrieval is viable and removes the model-download risk at demo time
- **LLM: OpenCode Zen free endpoint — no API key needed.** `ChatOpenAI(base_url="https://opencode.ai/zen/v1", api_key="public")` with `deepseek-v4-flash-free` (verified: chat + tool calling work through both raw SDK and LangChain). Eliminates the "bring your own key" dependency entirely
- **Agent framework: langchain-openai + LangGraph.** Verified end-to-end: `create_agent` loop with bound tools against the free endpoint. LangGraph buys: tool-calling loop, state/checkpointing, streaming, and a clean story for the "agentic design" interview axis
- **Not used:** LangServe (FastAPI wraps the compiled graph directly — fewer deps, one API surface) and LangSmith (needs its own account/key; not free via zen — only adds observability, optional later)
- **UI:** simple single-page chat (React/Vite or vanilla)

## 4. Build steps

### 1. Ingestion (`python -m spendiq.ingest`, idempotent)

- Load CSVs into normalized SQLite schema with FKs; sanitize empty-string FKs to NULL; validate dates; normalize non-USD amounts for aggregation
- Extract text from MD + PDF docs; chunk by section/clause; index chunks keyed by `(doc_id, chunk_id, source, clause_text)` with keyword index + optional embeddings
- Create **analytic SQL views** (data-modeling, not extra tools) so Tier 3/4 questions reduce to one simple query each:
  - `v_invoice_terms_vs_contract` — invoices billed shorter than contract terms
  - `v_contract_spend_vs_cap` — cumulative invoice spend vs total_value_cap_usd
  - `v_split_purchase_orders` — same vendor/dept/date clusters under the $10K approval threshold (policy: prohibited)
  - `v_contract_expiry` — end_date + auto_renew + notice_period_days, days-to-expiry from reference date
  - `v_vendor_spend_no_active_contract` — >$50K YTD spend, no active contract
  - `v_duplicate_invoices` — same vendor, similar amount, last 6 months
- Rerun-safe (drop/recreate), target ~90s total

### 2. Agent: exactly 2 tools + citation-aware answers

- `query_structured_data(sql)` — read-only SQL, schema + view list injected into system prompt, results as JSON/table
- `retrieve_documents(query, doc_filter)` — hybrid keyword + vector retrieval, top-k chunks with doc IDs and clause text
- System prompt rules:
  - Cite invoice IDs / contract IDs / document + clause in every answer
  - State which tool produced each part of the answer
  - **Ambiguous question → ask a clarifying question or state the assumption made** (evaluation axis: "handling of ambiguous questions")
  - Don't invent numbers; answer "unknown" explicitly when a tool returns nothing
- Conversation memory: LangGraph checkpointing (in-memory for POC) so follow-ups like "and which of those are auto-renewing?" work

### 3. Chat UI

Text input, message history, per-answer "Sources & Tools" panel (which tool ran, which docs/IDs cited). No auth, no streaming polish.

### 4. Validation

Scripted end-to-end run of ~8 questions covering all 4 tiers, including the verified anomalies above, before submission. Also test an ambiguous question to confirm the clarifying-question behavior.

### 5. Docs (deliverables)

- `README.md` — clean-clone run instructions: `uv sync && cp .env.example .env && make ingest && make run`
- `DESIGN_NOTES.md` — architecture, schema decisions, chunking/embedding choices, how tools were exposed to the agent, limitations (SQLite not pgvector, no auth, single-user, FX normalization shortcut), what would change at 10x scale

## 5. Risks & fallbacks

- **Free zen endpoint rate limits/outage:** provider is abstracted behind one env config; `.env` supports a paid fallback key if the interviewer offers one. `--mock` flag keeps the UI renderable as a last resort
- **Model download blocked (embeddings):** keyword-first retrieval is the primary path, so retrieval never blocks ingestion
- **uv/Python pin:** interpreter pinned to 3.12 in `pyproject.toml` so a clean clone resolves identically
- **Tool-calling regression on free model:** verified today (deepseek-v4-flash-free); if it regresses, swap model ID via env (e.g. `gpt-5-nano`, `ling-3.0-flash-free`) without code changes

## 6. Milestones (2h)

| Time   | Milestone |
| ------ | --------- |
| 0:00–0:15 | Setup, scaffold, sketch |
| 0:15–0:45 | Ingestion done (DB + docs + views) |
| 0:45–1:15 | Agent + 2 tools wired |
| 1:15–1:45 | UI + end-to-end verification on sample questions |
| 1:45–2:00 | Design notes, cleanup, submit |
