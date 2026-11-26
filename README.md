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
make test       # pytest (starts the Compose postgres unless RULEBOOK_TEST_DATABASE_URL is set)
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

## Run the rulebook API

```bash
make up          # builds the image, starts postgres, applies migrations, serves :8000
```

Store both golden catalogs (version and language are read from the catalog metadata):

```bash
curl -s -X POST localhost:8000/catalogs -H 'content-type: application/json' \
  --data-binary @data/catalogs/dadm-section6.en.json
curl -s -X POST localhost:8000/catalogs -H 'content-type: application/json' \
  --data-binary @data/catalogs/dadm-section6.fr.json
curl -s localhost:8000/catalogs
```

| Endpoint | Purpose |
|---|---|
| `POST /catalogs[?name=&lang=]` | Store a catalog version (validated, immutable; 409 if the version exists with other content) |
| `GET /catalogs` | Catalogs, versions and languages |
| `GET /catalogs/{name}/versions/{version}?lang=` | The stored OSCAL document |
| `GET /controls/{id}?version=&catalog=&lang=` | One control (latest version by default) |
| `POST` or `GET /catalogs/{name}/diff?from=&to=&lang=` | Added / retired / changed controls with field-level changes |
| `POST /catalogs/{name}/versions/{v}/retire-control/{id}` | New minor version (all languages) with the control marked `status = withdrawn` |

Rules enforced on every new version: OSCAL 1.1.3 schema validation; versions only increase;
a control may not disappear (retire it instead); reusing an ID for a different clause label
returns a warning; EN and FR versions with the same number must have identical control IDs.
The database also refuses `UPDATE`/`DELETE` on stored versions.

## Run a diff

Retire a control, then diff the two versions:

```bash
curl -s -X POST localhost:8000/catalogs/dadm-section6/versions/1.0.0/retire-control/DADM-6.3.5
curl -s "localhost:8000/catalogs/dadm-section6/diff?from=1.0.0&to=1.1.0" | jq
```

To see an `obligation-change` flag, publish a version whose statement changes an obligation
word. The edit below is **synthetic demo data, not policy text** (needs `jq`):

```bash
curl -s localhost:8000/catalogs/dadm-section6/versions/1.1.0 \
  | jq --arg uuid "$(python3 -c 'import uuid; print(uuid.uuid4())')" '
      .catalog.uuid = $uuid
      | .catalog.metadata.version = "1.2.0"
      | (.catalog.groups[].controls[] | select(.id == "DADM-6.2.2-A") | .parts[0].prose)
        = "Notices must be displayed prominently."' \
  | curl -s -X POST localhost:8000/catalogs -H 'content-type: application/json' --data-binary @-
curl -s -X POST "localhost:8000/catalogs/dadm-section6/diff?from=1.1.0&to=1.2.0" | jq
```

The changed control carries `"flags": ["obligation-change"]`, with `obligations_before: []`
and `obligations_after: ["must"]`. Obligation words: EN must, shall, should, may, required;
FR doit, doivent, peut, peuvent, est tenu(e).

<!-- TODO(milestone-1): profiles (commit 6). -->
