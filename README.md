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
services/connector-hub/      Milestone 3: ServiceNow inventory and tasks (MLflow, open API: later)
services/assessment-engine/  Milestone 5: rule-based checks in code, judgment checks drafted by a model
services/review-desk/        Milestone 3: review queue, hash-chained log, POA&M, forecast
services/control-centre/     Milestone 4: bilingual web UI for the demo (OIDC, tenants: later)
shared/                      common models, OSCAL helpers, model-gateway interface (stub)
data/golden/                 hand-mapped golden set (CSV) — the only source of check wording
data/sources/                source-document registry + metadata-only JSON (raw/ is gitignored)
data/inventory/              fictional AI-system inventory (CSV)
data/config/                 due-date policy (PLACEHOLDER values)
data/demo/                   SYNTHETIC demo: Directive on Example Widgets, its catalogs and profiles
data/catalogs/               generated OSCAL catalogs (EN and FR)
schemas/                     vendored NIST OSCAL 1.1.3 JSON schemas
docs/                        design notes
```

## Status: Milestones 1 to 6

| Done | Item |
|---|---|
| ✅ | Golden-set importer → EN and FR OSCAL 1.1.3 catalogs, schema-validated, EN/FR parity, reproducible |
| ✅ | Rulebook API: immutable versions in PostgreSQL, diff with `obligation-change`, retire, control lookup |
| ✅ | Profiles: example Level II+ profile and resolver |
| ✅ | **M2** Source documents: official text imported from local files (never committed), clause diff with renumbering, splits, obligation changes and EN/FR cross-check |
| ✅ | **M2** Clause-to-control links, suggestion report, fictional inventory, impact report with ranked systems and ServiceNow-shaped tasks |
| ✅ | **M3** connector-hub (ServiceNow inventory and tasks, mock ServiceNow), review-desk (ranked queue, five decisions, hash-chained log, OSCAL POA&M, forecast) |
| ✅ | **M4** control-centre web UI in English and French: policy change, impact report, review queue with the five decisions, decision log with external checkpoints, inventory; WCAG 2.1 AA basics, axe-scanned end-to-end test in CI |
| ✅ | **M5** assessment-engine: evidence upload (encrypted), rule-based checks in code, judgment checks drafted by a self-hosted model with prompt-injection defences, OSCAL assessment-results; accuracy harness (Appendix B) and release gate, EN and FR; CI uses a scripted fake model only |
| ✅ | **M6** rulebook drafts: a policy change is planned into control changes by plain code, drafted per language by the self-hosted model with safeguards, edited/approved/rejected by people in the bilingual "Rulebook drafts" screen (governance officers approve; two-person rule), published as a new catalog version with provenance and a hash-chained approval log; drafting accuracy harness and release gate |
| ⏳ later | sign-in (OIDC), tenants |

Definition of done, checked in CI on every push: `make setup && make test` on a clean
checkout, both catalogs validate, committed catalogs match the CSV, and `make up` serves the
API (the container job builds the image, starts it with PostgreSQL, stores the catalogs,
retires a control, diffs and resolves the example profile).

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

## Profiles (and stored profiles)

An OSCAL profile selects and tailors controls; resolving it gives a flat catalog that the
assessment engine will evaluate. `data/profiles/dadm-level-ii-plus.json` is an
**illustrative** Level II+ baseline that selects controls by ID (impact-level selection waits
for the Appendix C mapping):

```bash
uv run rulebook resolve-profile data/profiles/dadm-level-ii-plus.json --ids   # control IDs
uv run rulebook resolve-profile data/profiles/dadm-level-ii-plus.json --out /tmp/resolved.json
```

Through the API, import hrefs name stored catalog versions:

```bash
jq '.profile.imports[0].href = "/catalogs/dadm-section6/versions/1.0.0?lang=fr"' \
  data/profiles/dadm-level-ii-plus.json \
  | curl -s -X POST localhost:8000/profiles/resolve -H 'content-type: application/json' \
      --data-binary @- | jq .control_ids
```

Supported: `include-all`, `include-controls`/`exclude-controls` (`with-ids`, `matching`),
`merge` as-is or flat, `modify.set-parameters`. Unsupported features (`alters`, custom
merge, profile-to-profile imports) fail loudly. Withdrawn controls are never included.
Resolution never fetches anything over the network.

Stored profiles: `PUT /profiles/{name}` (the `profile-name` metadata prop must match),
`GET /profiles`. Systems in the inventory refer to profiles by name.

## Source documents (official policy text)

Official policy text is supplied by the deploying organization; EGCS does not distribute it.
**Never commit it.** Put pages saved from the Treasury Board site in `data/sources/raw/`
(gitignored and excluded from Docker builds), named `<instrument>.<YYYY-MM-DD>.<en|fr>.html`,
for example `dadm.2025-06-24.en.html`:

```bash
uv run rulebook import-source data/sources/raw/dadm.2025-06-24.en.html --retrieved 2026-11-27
```

This writes the full document (with text) beside the raw file, and a **metadata-only** file
(`data/sources/dadm.2025-06-24.en.meta.json`: file hash, clause numbers and hashes, no text),
which is the only part that may be committed. Real-text tests run locally and are skipped,
with a message, when the raw files are absent. Load the full document into a deployment:

```bash
curl -s -X POST localhost:8000/sources -H 'content-type: application/json' \
  --data-binary @data/sources/raw/dadm.2025-06-24.en.json
```

Clause diff between two versions (EN and FR, with an EN/FR cross-check):

```bash
curl -s "localhost:8000/sources/dadm/diff?from=2023-04-24&to=2025-06-24&lang=both" | jq .en.summary
```

Every pair reports its status (`unchanged`, `renumbered`, `changed`, `changed-renumbered`),
the method (`exact`, `similarity`, `containment`), score and flags (`renumbered`,
`text-changed`, `typography-only`, `obligation-change`, `split`, `merge`); splits, merges,
added and removed clauses are listed separately. Each response states the matching method
and thresholds (see `docs/decisions.md` #35–36). French typography (no-break spaces,
guillemets, apostrophes, ligatures) is ignored for matching but never altered.

## Linking checks to source clauses

The golden-set column **"Source clauses"** lists the clause numbers (in the source version
named by `SOURCE_VERSION` in the settings file) each check comes from, separated by `;`.
Empty means "no links yet" and is listed in the import report. To help annotators, rank
candidate clauses for each check (review CSV only; nothing is written back):

```bash
uv run rulebook suggest-source-clauses data/golden/dadm-section6.csv \
  --source data/sources/raw/dadm.2025-06-24.en.json --top 3 --out data/sources/raw/suggestions.csv
```

## Inventory and impact report

`data/inventory/systems.csv` is a **fictional** inventory (8 systems, 3 tenants, impact
levels I–IV). Load it, then ask for an impact report from a source change, a catalog change
(controls edited directly), or both:

```bash
curl -s -X PUT "localhost:8000/inventory?source=systems.csv" -H 'content-type: text/csv' \
  --data-binary @data/inventory/systems.csv
curl -s -X POST localhost:8000/impact-reports -H 'content-type: application/json' -d '{
  "catalog": "example-widgets", "catalog_version": "1.0.0",
  "source": {"instrument": "example-widgets", "from": "2023-01-01", "to": "2025-01-01"},
  "as_of": "2026-12-01"}' | jq .summary
```

The report lists affected controls with reasons, systems ranked by impact level, one
reassessment task per system shaped like a ServiceNow `sc_task` (returned, not sent), and
rulebook maintenance items (renumbered references, unmapped clauses, EN/FR divergences,
retired controls). Due dates come from `data/config/due-dates.toml`, whose values are
**PLACEHOLDERS, not policy**. The same inputs always give the same report.

## Demo: policy diff → impact report (synthetic)

```bash
make up
make demo        # scripts/demo-impact.sh http://localhost:8000 demo-output
```

The demo loads the synthetic Directive on Example Widgets (two versions, EN/FR), its linked
catalog, the profiles and the fictional inventory, then prints the clause diff (a renumbered
block, a split and a should → must change) and the ranked impact report with its tasks.
CI runs the same script on every push. Everything it uses is fictional; see
`data/demo/README.md`.

## Milestone 3: from a task to a human decision

| Service | Port (Compose) | Role |
|---|---|---|
| rulebook | `localhost:8000` | rules, sources, inventory, impact reports |
| connector-hub | `127.0.0.1:8001` | the **only** service that calls out, and only to `CONNECTOR_ALLOWED_HOSTS` |
| review-desk | `127.0.0.1:8002` | review queue, decisions, decision log, POA&M, forecast |
| mock ServiceNow | `127.0.0.1:8003` | Table API stand-in for tests, CI and the demo |

> **review-desk trusts placeholder identity headers** (`X-GovHub-User`, `X-GovHub-Role`)
> until control-centre adds OIDC. Keep it on localhost or the internal network; never
> expose it.

```bash
make up
make demo          # rule change -> impact report (M2)
make demo-review   # inventory from ServiceNow -> tasks -> decisions -> verified log -> POA&M -> forecast
```

### ServiceNow

Set up your developer instance with `docs/servicenow-setup.md` (role
`u_govhub_task_writer`, table `u_govhub_task` extending `task`, two fields on
`cmdb_ci_business_app`, an integration user). Then, on your machine only:

```bash
cp .env.servicenow.example .env.servicenow    # gitignored; never commit credentials
make servicenow-check                         # read inventory, create/update/close a smoke task
uv run connector-hub sync-inventory --dry-run
```

`POST :8001/inventory/sync` pulls the AI systems (missing fields become data gaps and
data-gap tasks, never errors); `POST :8001/tasks/sync-impact-report` creates or updates
one task per impact-report task, matched by `correlation_id`, so re-running is safe.

### Review desk

- `POST /intake/impact-report`: one finding per affected system × control. Until the
  assessment engine exists, every finding is a **placeholder** (`unable-to-determine`, no
  confidence).
- `GET /queue`: ranked by impact level, verdict severity, uncertainty, due date.
- `POST /findings/{id}/open`, then `POST /findings/{id}/decisions` with `accept`,
  `accept-with-remediation` (adds an OSCAL POA&M item and a remediation task),
  `reject`, `request-more-evidence` (evidence task) or `override-verdict`.
- Every decision is one record in an **append-only, hash-chained log**:

```bash
docker compose exec review-desk review-desk verify-log        # or GET :8002/decision-log/verify
docker compose exec review-desk review-desk checkpoint        # keep (seq, hash) outside the hub
docker compose exec review-desk review-desk export-log --out /tmp/log.jsonl
```

  `verify-log --file export.jsonl --expect-seq N --expect-head HASH` checks an export
  and detects records removed from the end. The database refuses UPDATE, DELETE and
  TRUNCATE on the log.
- **Checkpoints outside the database:** after every decision (or every N,
  `REVIEW_DESK_CHECKPOINT_EVERY`; 0 = off) the head (seq, hash) is written as a work note
  on the finding's `u_govhub_task` and appended to `REVIEW_DESK_CHECKPOINT_FILE`
  (Compose: its own `checkpoints` volume, not the database's). Trust them when verifying:
  `verify-log --trust-file [PATH] --trust-servicenow`, or
  `GET /decision-log/verify?trust=file&trust=servicenow`; `GET /decision-log/checkpoint-status`
  compares the latest checkpoint from each source with the database. A database owner who
  switches the triggers off and deletes the newest records is then still detected.
- `GET /poam/{system}`: the system's OSCAL 1.1.3 POA&M (every version kept).
- `POST /forecast` (impact report) or `GET /forecast` (open queue): reviewer hours per
  tenant against weekly capacity. Until 20 timed decisions exist, the rate is the
  **PLACEHOLDER** 20 minutes per finding (`data/config/review-rate.toml`).

## Milestone 4: the demo web UI (control-centre)

**Demo only: no authentication.** The UI acts as the placeholder reviewer
`demo-reviewer-01` and is published on `127.0.0.1:8004` only; never expose it.

```bash
make up              # includes control-centre on http://127.0.0.1:8004
make demo-review     # loads the synthetic directive, fictional systems, findings, decisions
```

Open <http://127.0.0.1:8004/> and choose English or Français. The five screens, in demo
order: **1** policy change (side-by-side clause diff with renumbered, split and
obligation-change flags), **2** impact report (affected controls, ranked systems,
ServiceNow tasks, forecast and capacity), **3** review queue (open a finding, start the
timed review, record one of the five decisions), **4** decision log (verify the chain and
the checkpoints kept in a file and in ServiceNow), **5** system inventory (data gaps).

The look loosely follows Canada.ca but carries no Government of Canada logos, wordmark,
flag symbols or "Canada.ca" text; every page says it is a prototype by Envision Global
Consultancy Services Inc. and not a Government of Canada website. Screens with the
Directive on Example Widgets say "Synthetic test data, not real policy"; inventory
screens say "Fictional systems and owners".

French UI strings: `docs/fr-ui-strings.md` (unverified unless marked provided by the
project owner).

End-to-end test (Chromium, axe-core accessibility scan of every screen in both
languages, keyboard-only decision, no request to any other host):

```bash
uv run playwright install chromium   # once
make demo-ui                         # writes e2e-output/: screenshots, axe results, timings
```

CI runs it after the other demos and keeps `e2e-output/` as the `ui-e2e-output` artifact.

## Milestone 5: assessment engine and accuracy harness

The engine assesses each open finding. Rule-based checks are plain code against facts
recorded for the system (`data/rules/*.rules.toml`, unverified drafts for the annotators).
Judgment checks are drafted by a **self-hosted** model from the best evidence passages.
The result is one of five verdicts, a confidence score, a word-for-word quote from the
evidence, and the reasoning in English and French. Anything unsupported or below the
**PLACEHOLDER 0.70** confidence threshold becomes *unable to determine*. The model never
closes a finding: drafts replace the placeholders in the review queue and a person decides.

- Evidence is untrusted. It goes to the model only as delimited data. Instruction-like
  text (English and French) is flagged and shown on the finding page, and a *met* verdict
  is never accepted while flagged text is in front of the model.
- Evidence may be personal or Protected. It is stored only on its own volume, encrypted by
  the service when `ASSESSMENT_EVIDENCE_KEY` is set (and by the platform where it allows),
  and never logged. Retention is a PLACEHOLDER for control-centre.
- Each run is also an OSCAL 1.1.3 **assessment-results** document, validated against the
  NIST schema.

```bash
make demo-assessment   # after make up and make demo-review: drafts on synthetic evidence
make accuracy          # harness on the synthetic cases (recorded replies) + release gate
```

The Compose stack uses a **scripted fake model** (recorded replies, no real model). To use
a real one, see **docs/model-setup.md** (llama.cpp on CPU with Qwen3-4B/8B; vLLM on a GPU
VM with Mistral Small 3.2 24B). Labelled cases for the harness: **docs/accuracy-cases.md**.
Scores are per language, human-labelled and synthetic never mixed, and labelled
**DRAFT GOLDEN SET** until the golden set is confirmed.

## Milestone 6: AI-drafted control changes, approved by people

When a directive changes, the rulebook plans the work from the clause diff with plain code:
an **edit** per linked control whose clause changed (splits and merges included), a
**new** control per added clause, a **retirement** per removed clause, and a
**clause-reference update** where only the numbering changed (no model for the last two).
The assessment engine drafts each edit and new control **separately in English and in
French**, from that language's own text, with the same safeguards as assessments: clause
text goes to the model only as delimited data and instruction-like text is never sent; the
draft must quote the new clause word for word; low confidence, an unreadable reply or a
"no change" for a new clause sends the draft to a person; plain code checks the drafted
obligation against the clause and flags a mismatch.

People decide in **"Rulebook drafts"** (control-centre, screen 6): the current control, the
clause change and the draft side by side, in the page language. Reviewers and governance
officers edit; **only a governance officer approves**, and **the person who last edited a
draft cannot approve it** (two-person rule, enforced by the rulebook, the reason shown on
the screen). Publishing makes a new minor catalog version (stored versions never change)
whose controls carry `drafted-by`, `approved-by` and `approval-record`; approval does not
make a control *reviewed*. The SOURCE_DATE defaults to the later of the policy's effective
date and the day after the previous one, and the screen refuses any date the guard would.
New controls get neutral IDs `<prefix>-C<nnn>` that are never reused. The golden set stays
the record: `rulebook apply-drafts` writes the published change set into the CSV, which
re-imports to exactly the stored version.

```bash
make demo-drafts   # LAST, after make demo-ui: plan, draft (fake model), approve in the UI,
                   # publish 1.1.0, impact report of 1.0.0 -> 1.1.0; writes e2e-output/drafts/
make accuracy      # also runs the drafting harness: recall, precision, obligation accuracy
```

Drafting accuracy (requirement recall, draft precision, obligation accuracy, per language)
is measured against expected drafts written by annotators (**docs/accuracy-cases.md**,
template `data/accuracy/template/drafting-cases.csv`); the committed synthetic ones only
check the pipeline.
