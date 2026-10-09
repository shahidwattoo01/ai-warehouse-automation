.PHONY: help setup lint format typecheck test test-fast api twin sim contracts tree up down clean
PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

help:  ## List commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

setup:  ## Create the virtual environment and install dependencies
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -U pip
	$(BIN)/pip install -e ".[dev]"
	$(BIN)/pre-commit install

lint:  ## Lint
	$(BIN)/ruff check src tests scripts

format:  ## Format
	$(BIN)/ruff format src tests scripts

typecheck:  ## Type check the package
	$(BIN)/mypy

test:  ## Full test suite
	$(BIN)/pytest

test-fast:  ## Skip slow tests
	$(BIN)/pytest -m "not slow and not integration"

api:  ## Start the API with reload
	$(BIN)/uvicorn warehouse_ai.api.main:app --reload --port 8000

twin:  ## Start the 3D twin
	cd apps/twin && npm install && npm run dev

sim:  ## Run one headless simulation
	$(BIN)/python scripts/run_sim.py --scenario configs/scenarios/normal.yaml

contracts:  ## Regenerate JSON Schemas and TypeScript types
	$(BIN)/python scripts/build_contracts.py

tree:  ## Regenerate docs/STRUCTURE.md
	$(BIN)/python scripts/make_tree.py

up:  ## Start everything with Docker Compose
	docker compose -f docker/docker-compose.yml up --build

down:  ## Stop Docker Compose
	docker compose -f docker/docker-compose.yml down

clean:  ## Remove caches
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
