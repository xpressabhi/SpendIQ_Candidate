PYTHON := uv run python
PY := uv run

.PHONY: install ingest run dev test

install:
	uv sync

ingest:
	$(PY) -m spendiq.ingest

run:
	$(PY) -m uvicorn spendiq.api:app --host 127.0.0.1 --port 8000

dev:
	$(PY) -m uvicorn spendiq.api:app --host 127.0.0.1 --port 8000 --reload

test:
	$(PY) -m pytest
