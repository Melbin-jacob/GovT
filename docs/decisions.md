# Decision log

| # | Date | Decision | Why |
|---|------|----------|-----|
| 1 | 2026-11-26 | FR catalog: French statement from `Contrôle (FR)`; FR guidance, objective and reviewed statement only from optional columns `S'applique lorsque`, `Preuves attendues`, `Libellé final convenu`, otherwise omitted. Parity compares control IDs. | Never translate or invent policy text. |
| 2 | 2026-11-26 | Review status is per language: `reviewed` only when that language's agreed-wording column is filled. | An English review does not review the French. |
| 3 | 2026-11-26 | Retiring a control creates a new minor version with prop `status = withdrawn`; the control stays in the catalog. | Stored versions are immutable; history is kept. |
| 4 | 2026-11-26 | Example profile selects controls by ID. | No structured impact level yet; an impact-level column will come with the Appendix C mapping. |
| 5 | 2026-11-26 | Diff exposed as `POST` (as specified) plus a `GET` alias. | The diff is read-only. |
| 6 | 2026-11-26 | Numbering column split: status word before any colon → `numbering-status`; text after the colon → `numbering-note`. | Keep the status machine-filterable and the note intact. |
| 7 | 2026-11-26 | Group derived from the first section number in the Clause column (`6.3.x` → `6.3`); a row with no group fails the import. | Some IDs carry no section (e.g. `DADM-SECURITY`). |
| 8 | 2026-11-26 | Catalog top-level `uuid` derived from a content hash. | OSCAL expects a new document uuid per revision; re-runs stay byte-identical. |
| 9 | 2026-11-26 | OSCAL library: compliance-trestle 3.12.4 (OSCAL 1.1.3). Rejected: trestle 4.x/5.x (OSCAL 1.2.1); oscal-pydantic 2023.3.21 (generated 2023-03-16, before OSCAL 1.1; fails to import under Pydantic v2). Trestle's `pydantic.v1` models stay inside `govhub_shared.oscal`. | Matches the pinned OSCAL version. |
| 10 | 2026-11-26 | Starlette's "use `httpx2`" TestClient deprecation warning is filtered in pytest; no switch to `httpx2` until reviewed. | Pending a decision on adopting a new HTTP client. |
