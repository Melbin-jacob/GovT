# Canadian AI Governance Hub

Prototype for the Shared Services Canada AI governance challenge. The hub turns governance
rules into versioned, machine-readable OSCAL 1.1.3 checks, detects rule changes, flags affected
AI systems, assesses them and records every human decision in a tamper-evident log.
An AI model only drafts; a human always decides.

**Milestone 1** delivers the **rulebook** service and the **golden set** for section 6 of the
Directive on Automated Decision-Making. See `CLAUDE.md` for project conventions.

## Layout

```
services/rulebook/           Milestone 1: OSCAL catalogs, profiles, diffs (FastAPI)
services/connector-hub/      later: ServiceNow, MLflow, open API
services/assessment-engine/  later: five-verdict assessments
services/review-desk/        later: review queue, evidence vault, hash-chained log, POA&M
services/control-centre/     later: OIDC, roles, tenants, residency, bilingual UI
shared/                      common models, OSCAL helpers, model-gateway interface (stub)
data/golden/                 hand-mapped golden set (CSV) — the only source of check wording
data/catalogs/               generated OSCAL catalogs (EN and FR)
schemas/                     vendored NIST OSCAL 1.1.3 JSON schemas
docs/                        design notes
```

## Prerequisites

- [uv](https://docs.astral.sh/uv/) 0.11+ (installs Python 3.12 if needed)
- Docker with Compose v2 (for `make up` and for the database used by the API tests)

## Setup

```bash
make setup      # uv sync of every workspace package + dev tools
make lint       # ruff
make typecheck  # mypy (strict for shared and rulebook)
make test       # pytest
make up         # postgres + rulebook API on http://localhost:8000
make down
```

Health checks: `GET /health` (process up) and `GET /ready` (database reachable).
Interactive API docs: http://localhost:8000/docs.

<!-- TODO(milestone-1): importing the golden set and running a diff (commits 4–5). -->
