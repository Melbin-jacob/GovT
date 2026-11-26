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

## Import the golden set

`data/golden/dadm-section6.csv` is the hand-mapped golden set for section 6 of the
Directive on Automated Decision-Making. The importer turns it into two OSCAL 1.1.3 catalogs
with identical control IDs, validates both against the vendored NIST schema and checks
EN/FR parity:

```bash
make import-golden
# same as: uv run rulebook import-golden data/golden/dadm-section6.csv
```

Outputs: `data/catalogs/dadm-section6.en.json` and `data/catalogs/dadm-section6.fr.json`.
Group titles come from `data/golden/dadm-section6.groups.csv`; `last-modified` comes from
`SOURCE_DATE` in `data/golden/dadm-section6.settings.toml` (bump it when the CSV changes).
Options: `--version` (semantic version, default `1.0.0`), `--out-dir`, `--name`, `--groups`,
`--settings`, and `--check` (write nothing; exit 1 if the committed catalogs are out of date).
The output never depends on the clock: a fresh import reproduces the committed files byte for
byte, and any content change gives the catalog a new `uuid`.

The importer fails, listing every problem, on: missing columns, blank or duplicate IDs,
IDs that are not OSCAL tokens, blank EN/FR check text, an unknown Numbering status or Check type, or a Clause
with no section number. Rows marked `Verify` and non-numeric clause labels are reported as
warnings.

<!-- TODO(milestone-1): running a diff (commit 5). -->
