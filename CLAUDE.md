# CLAUDE.md — Canadian AI Governance Hub

Conventions for anyone (human or AI) working in this repo. Read before changing code.
Design decisions and their reasons are logged in `docs/decisions.md`.

## What this is
A prototype for the SSC AI governance challenge. It turns governance rules into versioned
OSCAL checks, detects rule changes, flags affected AI systems, assesses them with five
verdicts plus a confidence score, and logs every human decision in a hash-chained record.
**An AI model only drafts; a human always decides.**

## Stack (fixed)
- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL 16.
- uv workspace (`uv.lock` is committed; use `uv sync --all-packages --frozen`).
- ruff (lint + format), mypy **strict** for `shared` and `rulebook`, pytest.
- Docker Compose for local dev only. Everything must run as plain containers on
  Kubernetes/OpenShift: no cloud-specific services, non-root images that work under an
  arbitrary UID. **Only connector-hub may make outbound calls, and only to hosts listed in
  its configuration; nothing else ever calls out.** (Calls between hub services inside the
  deployment are internal.)

## Layout
- `services/<name>/` — one folder per service: connector-hub, rulebook, assessment-engine,
  review-desk, control-centre. Implemented: rulebook (M1–2), connector-hub and review-desk (M3),
  control-centre demo UI (M4; sign-in still TODO).
- `shared/` — `govhub_shared`: constants, OSCAL helpers, model-gateway interface.
- `data/golden/` — hand-mapped golden set CSVs. `data/catalogs/` — generated catalogs.
  `data/profiles/` — OSCAL profiles.
- `schemas/` — vendored NIST OSCAL JSON schemas (see `schemas/oscal-1.1.3/SOURCE.md`).
- `data/sources/` — source registry and metadata-only JSON; `raw/` (official text) is gitignored.
- `data/inventory/` — fictional inventory; `data/config/` — PLACEHOLDER due dates.
- `data/demo/` — synthetic demo data (Directive on Example Widgets). Keep it obviously fictional.
- `docs/` — design notes and the decision log.

## OSCAL rules
- **OSCAL version is pinned to 1.1.3** (`govhub_shared.OSCAL_VERSION`). Use
  compliance-trestle **3.12.4** exactly; trestle 4.x/5.x target OSCAL 1.2.1.
- Every OSCAL artifact we write is validated against the vendored NIST 1.1.3 JSON schema.
  A validation error is a failure, never a warning.
- Custom props always carry `ns: "https://egcsgroup.com/ns/oscal"` (`govhub_shared.OSCAL_NS`).
- **Trestle boundary:** trestle's models use the `pydantic.v1` compatibility layer. They are
  used only inside `shared/src/govhub_shared/oscal/`. That package converts to plain dicts or
  our own Pydantic v2 models before returning. No `trestle` or `pydantic.v1` import anywhere
  else.
- Document UUIDs: control/part identity is deterministic; the catalog's top-level `uuid` is
  derived from a hash of its content, so identical content gives an identical uuid and any
  change gives a new one.
- Group IDs are `dadm-6.1` … `dadm-6.5` (OSCAL tokens may contain dots but not start with a digit).

## Policy content rules
- **Never invent policy text.** The golden-set CSV is the only source of check wording.
  Do not paraphrase, translate or "fix" it in code. If text is missing, omit the field.
- **English and French are separate catalogs with identical control IDs.** The parity check
  fails if a control exists in one language and not the other.
- French guidance, assessment objective and reviewed statement come only from the optional
  CSV columns `S'applique lorsque`, `Preuves attendues`, `Libellé final convenu`. If absent,
  the FR fields are omitted (never filled with English).
- Review status: a control is `reviewed` only when that language's agreed-wording column is
  filled (EN: `Agreed final wording`; FR: `Libellé final convenu`); otherwise `draft`.
- **Control IDs are frozen once published.** Never regenerate or renumber them. Reusing an
  ID for a different clause label must raise a warning.
- **Removing a control is an explicit retire**: a new minor version in which the control
  stays, with prop `status = withdrawn`. Never a silent delete. Stored versions are immutable.
- Clause labels are stored as-is (e.g. `6.3.9 or 6.3.10`); do not normalize them.
- Controlled-vocabulary props (`check-type`, `numbering-status`, `review-status`) hold
  language-neutral codes in both catalogs; unknown CSV values fail the import.
- Generated files never depend on the clock: `last-modified` comes from `SOURCE_DATE` in the
  golden set's `.settings.toml`. Any commit that changes the golden-set CSV or groups file
  must advance `SOURCE_DATE` (CI: `rulebook check-source-date`).

## Official policy text (source documents)
- Official text is supplied by the deploying organization; EGCS does not distribute it.
  It lives only in `data/sources/raw/` (gitignored, excluded from Docker builds) and in a
  deployment's database. Commit only `*.meta.json` (numbers and hashes), never text.
- CI and tests use the synthetic "Directive on Example Widgets" under `data/demo/`. Tests
  on real text must skip with a clear message when the raw files are absent.
- Matching normalizes typography (`rulebook/sources/normalize.py`); stored text never is.

## Rulebook service rules
- A catalog version is (name, semantic version, language). Stored versions are immutable:
  the API returns 409 for changed content and a DB trigger refuses UPDATE/DELETE. Schema
  changes go through a new Alembic migration in `services/rulebook/src/rulebook/migrations`;
  always run them via `rulebook.migrate` (it holds an advisory lock for multi-replica safety).
- New versions must be newer than the latest; a control may not disappear (422) — retire it;
  an ID reused with a different clause label returns a warning.
- Obligation words are detected by plain code (`rulebook/obligations.py`), never by a model.
- Profile resolution is local only (`govhub_shared.oscal.profile`); unsupported profile
  features must fail loudly. Withdrawn controls are never resolved into a baseline.
- Tests that need PostgreSQL use `RULEBOOK_TEST_DATABASE_URL` (default: Compose DB on
  localhost); `make test` starts the Compose database if the variable is unset.
- Text written by an assistant that is not from the CSV (titles, remarks, example profile)
  is listed in `docs/decisions.md` as unverified.

## Impact reports
- Reports never read the clock (`as_of` is an input); `report_id` is a content hash.
- Renumbering or typography alone never triggers re-review; substance changes do.
- Tasks are returned as ServiceNow-shaped `sc_task` JSON, never incidents, and are not sent
  until connector-hub exists. Due-date values are PLACEHOLDERS until the organization sets them.

## Connectors and review desk
- ServiceNow credentials come from environment variables or a gitignored `.env.servicenow`;
  never commit them. CI and tests use the mock ServiceNow only.
- Hub tasks go to the custom table `u_govhub_task` (extends `task`), never `incident`.
- review-desk trusts placeholder identity headers until control-centre exists: bind it to
  localhost or the internal network only, never expose it.
- The decision log is append-only and hash-chained; never update or delete its rows.
  Its head is checkpointed outside the database (ServiceNow work note + checkpoint file on
  a separate volume); a checkpoint failure is reported, never blocks a decision.

## Web UI (control-centre)
- Server-rendered (FastAPI + Jinja2), plain forms; nothing loaded from another origin (CSP).
- Every UI string in both `locales/en.toml` and `locales/fr.toml`; French strings written by
  an assistant are unverified and listed in `docs/fr-ui-strings.md` (regenerate with
  `control-centre fr-strings docs/fr-ui-strings.md`; CI checks it). Policy wording comes
  from the catalogs, never from the UI strings.
- Never use Government of Canada logos, wordmark, flag symbols or "Canada.ca" text. Keep the
  demo banner, the bilingual footer and the synthetic/fictional notes.
- Demo only, no authentication: bind to localhost or the internal network only.
- `make demo-ui` (Playwright + axe) must pass with zero axe violations.

## AI usage
- All model access goes through `govhub_shared.model_gateway.ModelGateway`. Milestone 1 makes
  **no LLM calls** (`NullGateway` only). Self-hosted by default when added.

## Working rules
- Small commits with clear messages. Never put model identifiers in commits or code.
- Before saying something is done, run `make lint typecheck test` and report the results.
- Leave `TODO(<service>)` markers and interface stubs for out-of-scope work rather than
  half-implementing it (connectors, UI, auth, assessments).
- pytest runs with `filterwarnings = error`; filter a specific warning only with a comment
  explaining why.
