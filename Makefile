.PHONY: setup lint typecheck test up down check

setup:  ## Install all workspace packages and dev tools
	uv sync --all-packages --frozen

lint:  ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

typecheck:  ## mypy (strict for shared and rulebook)
	uv run mypy

test:  ## Run the test suite
	uv run pytest

check: lint typecheck test  ## Everything CI runs, except the container job

up:  ## Build and start postgres + rulebook (API on http://localhost:8000)
	docker compose up -d --build --wait

down:  ## Stop the stack
	docker compose down
