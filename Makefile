.PHONY: setup lint typecheck test up down check import-golden migrate demo demo-review demo-ui servicenow-check

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

import-golden:  ## Regenerate catalogs from the golden-set CSVs (real and synthetic demo)
	uv run rulebook import-golden data/golden/dadm-section6.csv
	uv run rulebook import-golden data/demo/golden/example-widgets.csv --out-dir data/demo/catalogs

migrate:  ## Apply database migrations to RULEBOOK_DATABASE_URL
	uv run rulebook migrate

demo:  ## Run the synthetic policy-diff -> impact-report demo against `make up`
	scripts/demo-impact.sh http://localhost:8000 demo-output

demo-review:  ## Run the task -> decision -> verified log -> POA&M demo against `make up`
	scripts/demo-review.sh demo-review-output

demo-ui:  ## Click through the web UI (EN/FR) in Chromium with axe scans; after `make demo-review`
	CONTROL_CENTRE_URL=$${CONTROL_CENTRE_URL:-http://127.0.0.1:8004} E2E_OUTPUT=e2e-output \
		uv run pytest services/control-centre/e2e -p no:cacheprovider

servicenow-check:  ## Check a REAL ServiceNow instance (.env.servicenow); never run in CI
	uv run connector-hub check-servicenow
