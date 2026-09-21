PYTHON ?= python3
QUALITY_PATHS := app tests scripts

.PHONY: check dependencies forge-check format format-check lint test

check: format-check lint dependencies forge-check test

dependencies:
	$(PYTHON) -m deptry . --exclude '.venv|node_modules|\.git' --optional-dependencies-dev-groups dev,test --known-first-party app --per-rule-ignores 'DEP002=starlette|uvicorn|pytest-asyncio|deptry|pre-commit|ruff,DEP004=pytest'

forge-check:
	npm --prefix forge run check

format:
	$(PYTHON) -m ruff format $(QUALITY_PATHS)

format-check:
	$(PYTHON) -m ruff format --check $(QUALITY_PATHS)

lint:
	$(PYTHON) -m ruff check $(QUALITY_PATHS)

test:
	$(PYTHON) -m pytest -q
