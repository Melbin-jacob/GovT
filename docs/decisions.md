# Decision log

| # | Date | Decision | Why |
|---|------|----------|-----|
| 1 | 2026-11-26 | FR catalog: French statement from `Contrôle (FR)`; FR guidance, objective and reviewed statement only from optional columns `S'applique lorsque`, `Preuves attendues`, `Libellé final convenu`, otherwise omitted. Parity compares control IDs. | Never translate or invent policy text. |
| 2 | 2026-11-26 | Review status is per language: `reviewed` only when that language's agreed-wording column is filled. | An English review does not review the French. |
| 3 | 2026-11-26 | Retiring a control creates a new minor version with prop `status = withdrawn`; the control stays in the catalog. | Stored versions are immutable; history is kept. |
| 4 | 2026-11-26 | Example profile selects controls by ID. | No structured impact level yet; an impact-level column will come with the Appendix C mapping. |
| 5 | 2026-11-26 | Diff exposed as `POST` (as specified) plus a `GET` alias. | The diff is read-only. |
| 6 | 2026-11-26 | Numbering column split: status word before any colon → `numbering-status` as a code (`confirmed`, `likely`, `verify`); text after the colon → `numbering-note` (free text) plus `numbering-note-lang = en`. | Keep the status machine-filterable and language-neutral; the note stays intact. |
| 7 | 2026-11-26 | Group derived from the first section number in the Clause column (`6.3.x` → `6.3`); a row with no group fails the import. | Some IDs carry no section (e.g. `DADM-SECURITY`). |
| 8 | 2026-11-26 | Catalog top-level `uuid` derived from a content hash. | OSCAL expects a new document uuid per revision; re-runs stay byte-identical. |
| 9 | 2026-11-26 | OSCAL library: compliance-trestle 3.12.4 (OSCAL 1.1.3). Rejected: trestle 4.x/5.x (OSCAL 1.2.1); oscal-pydantic 2023.3.21 (generated 2023-03-16, before OSCAL 1.1; fails to import under Pydantic v2). Trestle's `pydantic.v1` models stay inside `govhub_shared.oscal`. | Matches the pinned OSCAL version. |
| 10 | 2026-11-26 | Starlette's "use `httpx2`" TestClient deprecation warning is filtered in pytest; no switch to `httpx2` until reviewed. | Pending a decision on adopting a new HTTP client. |
| 11 | 2026-11-26 | Control `title` = Check ID. | OSCAL requires a title; the CSV has no title column and we do not write policy text. |
| 12 | 2026-11-26 | Group titles live in `data/golden/dadm-section6.groups.csv` (data, not code); group IDs are `dadm-6.1` … `dadm-6.5` (dots are valid in OSCAL tokens; a leading digit is not). FR titles are the official section headings of the French Directive, supplied and verified by the project owner. | Reviewable alongside the golden set. |
| 13 | 2026-11-26 | `last-modified` = `SOURCE_DATE` from `data/golden/dadm-section6.settings.toml`; the importer never reads the clock. Bump `SOURCE_DATE` whenever the CSV or groups file changes. | A fresh import into an empty folder is byte-identical to the committed catalogs. |
| 14 | 2026-11-26 | Annotator A/B, notes and "A and B" columns are required in the header but not mapped into the catalogs yet. | They are all blank today; mapping them waits for the agreement workflow. |
| 15 | 2026-11-26 | Controlled-vocabulary props are language-neutral codes in both catalogs: `check-type` ∈ {`rule-based`, `rule-based-roll-up`, `judgment`}, `numbering-status` ∈ {`confirmed`, `likely`, `verify`}, `review-status` ∈ {`draft`, `reviewed`}. The importer maps the CSV display values and fails on any unknown value. | The same code means the same thing in EN and FR, and diffs/filters don't depend on language. |
| 16 | 2026-11-26 | **Unverified, written by Claude Code:** the French catalog's `metadata.title` ("Directive sur la prise de décisions automatisée — contrôles de la section 6 (ensemble de référence)") and `metadata.remarks`, and the English catalog's `metadata.title` and `metadata.remarks`. These are descriptive metadata, not check wording. | Needs review by a French-language reviewer before external use. |
