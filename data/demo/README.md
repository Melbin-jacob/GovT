# Demo data — entirely synthetic

Everything under `data/demo/` is **fictional test data** written for this repository:
the "Directive on Example Widgets" (EN/FR, two versions), its golden set and catalogs,
and its profiles. It is not policy text and must never be presented as such.

The two versions are built to exercise the clause diff:

| Change (2023-01-01 → 2025-01-01) | Clauses |
|---|---|
| Unchanged | 6.1.1 (FR differs only in typography: œ/oe) |
| Wording change, no obligation change | 6.1.2 |
| Added | 6.2.1, 6.2.2 |
| Renumbered + obligation change (should → must) | 6.2.1 → 6.3.1 |
| Renumbered only (FR differs only in apostrophes) | 6.2.2 → 6.3.2, 6.2.3 → 6.3.3 |
| Split | 6.3.1 → 6.4.1 + 6.4.2 |
| Removed | 6.3.2 |
| Renumbered only | 6.4.1 → 6.5.1, 6.4.2 → 6.5.2 |

The expected mapping is recorded in `expected-diff.json` and checked by the tests.
