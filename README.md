# SpendIQ Copilot

A conversational copilot over Nimbus Retail's vendors, contracts, POs, and
invoices, with cross-reference to contract and policy documents. Python
3.12 + FastAPI + SQLite (FTS5) + LangGraph, using the **free OpenCode Zen
LLM endpoint** — no API keys required.

The dataset is anchored so that *today* is **2026-04-21**.

## Data

- `data/*.csv` — five structured files (departments, vendors, contracts,
  purchase_orders, invoices). Schema reference: `DATA_DICTIONARY.md`.
- `docs/contracts/` — 15 contract documents (12 Markdown, 3 PDF).
- `docs/policies/` — 3 policy documents (procurement, AP/expense, vendor risk).

## Requirements

- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 automatically)

## Setup

```bash
uv sync                      # install deps + Python 3.12 if needed
cp .env.example .env         # optional — defaults already work (free LLM)
make ingest                  # rebuild DB + document index from scratch (idempotent)
make run                     # start server on http://127.0.0.1:8000
```

Open http://127.0.0.1:8000 and chat. The UI shows which tools ran and which
documents were cited for each answer.

## Commands

| Command              | Purpose                                        |
| -------------------- | ---------------------------------------------- |
| `make ingest`        | Rebuild `data/spendiq.db` from CSVs + docs     |
| `make run`           | Start the FastAPI server (no reload)           |
| `make dev`           | Start with `--reload`                          |
| `make test`          | Run pytest (no LLM needed)                     |
| `make validate`      | End-to-end agent run over 12 tiered questions  |
| `make eval`          | Golden-set eval: 14 tiered cases, graded       |
| `make eval-stable`   | Same, 3 runs per case with majority voting     |

## Evals

`src/spendiq/evals/` is a golden-set evaluation harness. 14 tiered
questions (T1-T4) run through the real agent and are graded by
composable checks defined in `evals/cases.py`:

- `contains_all` / `contains_any` / `contains_none` — substring checks
- `regex` — `count_near(N, keyword)` accepts digits or spelled-out numbers
- `tool_used` — asserts the agent called the right tool
- `source_cited` — asserts a document ID appears in the agent's citations
- `llm_judge` — rubric graded by the LLM (opt-in with `--judge`)

Expected facts are grounded in the ingested dataset, so any regression
in retrieval, the analytic views, or prompting fails the suite.

Useful flags: `--tier T2`, `--case split_pos`, `--runs 3` (majority
vote to absorb LLM phrasing variance), `--json PATH` (machine-readable
report for CI). Graders themselves are unit-tested in
`tests/test_evals.py` (no LLM needed).

## Configuration (`.env`)

Defaults need zero setup — they point at the free OpenCode Zen endpoint:

| Variable        | Default                           |
| --------------- | --------------------------------- |
| `LLM_BASE_URL`  | `https://opencode.ai/zen/v1`      |
| `LLM_API_KEY`   | `public`                          |
| `LLM_MODEL`     | `deepseek-v4-flash-free`          |
| `SPENDIQ_MOCK`  | unset (set to `1` for offline UI) |

For the paid **OpenCode Go** plan (no free-tier rate limits), copy
`.env.example` to `.env` and set:
- `LLM_BASE_URL=https://opencode.ai/zen/go/v1` (Go models are served on the
  `/zen/go/v1` path — `/zen/v1` bills credits instead)
- `LLM_API_KEY` to your Go key (from https://opencode.ai/auth or the opencode
  `/connect` command)
- `LLM_MODEL=deepseek-v4-flash`

To use any other provider, point `LLM_BASE_URL`/`LLM_API_KEY` at an
OpenAI-compatible endpoint and set `LLM_MODEL`.

## Architecture

```
data/*.csv ──┐
             ├─► spendiq.ingest ──► data/spendiq.db
docs/*.md,   │                        ├─ normalized tables (5)
docs/*.pdf ──┘                        ├─ 6 analytic views (anomaly queries)
                                      └─ FTS5 index of 80 doc chunks
                          ┌───────────┴────────────┐
                          │  LangGraph agent        │
                          │  query_structured_data  │ (read-only SQL)
                          │  retrieve_documents     │ (FTS5 BM25)
                          │  calculate              │ (safe arithmetic)
                          │  date_utils             │ (date windows)
                          │  resolve_entity         │ (name → ID lookup)
                          └───────────┬────────────┘
                              FastAPI /api/chat ──► static chat UI
```

See `DESIGN_NOTES.md` for detailed decisions.
