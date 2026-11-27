.PHONY: setup lint typecheck test up down check import-golden migrate

setup:  ## Install all workspace packages and dev tools
	uv sync --all-packages --frozen

lint:  ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

typecheck:  ## mypy (strict for shared and rulebook)
	uv run mypy

test:  ## Run the test suite (starts the Compose postgres unless RULEBOOK_TEST_DATABASE_URL is set)
	@if [ -z "$$RULEBOOK_TEST_DATABASE_URL" ]; then docker compose up -d --wait postgres; fi
	uv run pytest

check: lint typecheck test  ## Everything CI runs, except the container job

up:  ## Build and start postgres + rulebook (API on http://localhost:8000)
	docker compose up -d --build --wait

down:  ## Stop the stack
	docker compose down

import-golden:  ## Regenerate data/catalogs from the golden-set CSV
	uv run rulebook import-golden data/golden/dadm-section6.csv

migrate:  ## Apply database migrations to RULEBOOK_DATABASE_URL
	uv run rulebook migrate
