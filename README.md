# SpendIQ: Candidate Package

Welcome, and thanks for taking on the SpendIQ challenge. Everything you need is in this folder.

## Start here

1. **`CANDIDATE_BRIEF.pdf`** (or `CANDIDATE_BRIEF.md`). Read this first. Scenario, goals, sample questions, ground rules, and the 2-hour milestone plan.
2. **`DATA_DICTIONARY.md`**. Schema and field reference. Keep this open while you build your ingestion.

## Data

- `data/*.csv`. Five structured files (departments, vendors, contracts, purchase_orders, invoices).
- `docs/contracts/`. 15 contract documents; 12 are Markdown, 3 are PDF. Your ingestion should handle both.
- `docs/policies/`. 3 policy documents (procurement, AP/expense, vendor risk).

**Reference date:** the dataset is anchored so that "today" is **2026-04-21**. Use this when interpreting questions like *"contracts expiring in the next 90 days"*.

## Ground rules (summary; see the brief for details)

- 2 hours, self-paced. Use the full window.
- AI coding assistants encouraged (Claude Code, Codex, Cursor, etc.). Be prepared to talk through where they helped and where they went wrong.
- Recommended stack: Python backend, Postgres (with `pgvector` if you want), Next.js / React frontend. Not enforced; use what you know.
- LLM provider: your choice, bring your own key. We can provide a short-lived Anthropic or OpenAI key at the interview if needed.
- Submit whatever you have at the 2-hour mark, even if partial. Clear thinking plus partial implementation beats a polished demo with weak design choices.

## Interview format

The interview is remote, over **Microsoft Teams** with screen share. You will run your app on your own machine and demo it live. Have everything pre-started 5 minutes before the call.

## What to submit

A zip (or private Git link) with:

- Your code
- Reproducible ingestion and run instructions in a project `README.md`
- A short `DESIGN_NOTES.md` covering architecture, key decisions, limitations, and what you would do with more time

Good luck, and have fun with it.

---

# SpendIQ Copilot — Run Instructions

A conversational copilot over Nimbus Retail's vendors, contracts, POs, and
invoices, with cross-reference to contract and policy documents. Python
3.12 + FastAPI + SQLite (FTS5) + LangGraph, using the **free OpenCode Zen
LLM endpoint** — no API keys required.

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
