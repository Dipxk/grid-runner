VENV ?= gr-env
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PORT ?= 8000

.PHONY: help setup run test test-fast bench docker clean

help:
	@echo "make setup   - create the virtualenv and install dev dependencies"
	@echo "make run     - start the simulation server at http://localhost:$(PORT)"
	@echo "make test    - run the full test suite (includes randomised collision runs)"
	@echo "make bench   - run the load test and write benchmarks/results.{json,md}"
	@echo "make docker  - build and start via docker-compose"

setup:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements-dev.txt

run:
	cd backend && ../$(PY) -m uvicorn app.server:app --host 127.0.0.1 --port $(PORT) --reload

test:
	cd backend && ../$(PY) -m pytest

test-fast:
	cd backend && ../$(PY) -m pytest -q \
		--deselect tests/test_no_collisions.py::test_zero_collisions_over_randomised_runs

bench:
	cd backend && ../$(PY) scripts/benchmark.py \
		--json ../benchmarks/results.json --markdown ../benchmarks/results.md

docker:
	docker compose up --build

clean:
	rm -rf $(VENV) backend/**/__pycache__ backend/.pytest_cache
