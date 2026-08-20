PYTHON := uv run python
PY := uv run

.PHONY: install ingest run dev test validate eval eval-stable

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

validate:
	$(PY) -m spendiq.validate

eval:
	$(PY) -m spendiq.evals

eval-stable:
	$(PY) -m spendiq.evals --runs 3
