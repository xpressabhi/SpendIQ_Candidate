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
