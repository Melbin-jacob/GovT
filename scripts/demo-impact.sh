#!/usr/bin/env bash
# Demo: policy diff -> impact report, on SYNTHETIC data only (Directive on Example Widgets,
# fictional inventory). Needs a running rulebook (e.g. `make up`), curl and python3.
#
#   scripts/demo-impact.sh [BASE_URL] [OUT_DIR]
#
# Writes source-diff.json and impact-report.json to OUT_DIR, prints a summary, and exits
# non-zero if the expected renumbering, split, obligation change or ranking is missing.
set -euo pipefail

BASE="${1:-http://localhost:8000}"
OUT="${2:-$(mktemp -d)}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$OUT"

# shellcheck source=lib/hub-token.sh
. "$ROOT/scripts/lib/hub-token.sh"
rulebook_tokens
post() { curl --fail-with-body -sS -X "$1" "$BASE$2" -H "$(rulebook_auth "$1" "$2")" -H "content-type: ${4:-application/json}" --data-binary "@$3"; }

echo "== 1. Store the synthetic source documents (EN/FR, 2023-01-01 and 2025-01-01)"
for f in "$ROOT"/data/demo/sources/example-widgets.*.json; do
  case "$f" in *.meta.json) continue ;; esac
  post POST /sources "$f" >/dev/null
  echo "   $(basename "$f")"
done

echo "== 2. Store the synthetic catalogs (controls linked to 2023-01-01 clauses)"
for lang in en fr; do
  post POST /catalogs "$ROOT/data/demo/catalogs/example-widgets.$lang.json" >/dev/null
done

echo "== 3. Store profiles and the fictional inventory"
for f in "$ROOT"/data/profiles/*.json "$ROOT"/data/demo/profiles/*.json; do
  post PUT "/profiles/$(basename "$f" .json)" "$f" >/dev/null
done
post PUT "/inventory?source=systems.csv" "$ROOT/data/inventory/systems.csv" text/csv >/dev/null

echo "== 4. Clause diff 2023-01-01 -> 2025-01-01 (EN and FR, with cross-check)"
curl --fail-with-body -sS -H "$(rulebook_auth GET /sources)" \
  "$BASE/sources/example-widgets/diff?from=2023-01-01&to=2025-01-01&lang=both&include_text=false" \
  > "$OUT/source-diff.json"

echo "== 5. Impact report"
cat > "$OUT/impact-request.json" <<JSON
{"catalog": "example-widgets", "catalog_version": "1.0.0",
 "source": {"instrument": "example-widgets", "from": "2023-01-01", "to": "2025-01-01"},
 "as_of": "2026-12-01"}
JSON
post POST /impact-reports "$OUT/impact-request.json" > "$OUT/impact-report.json"

python3 "$ROOT/scripts/demo_summary.py" "$OUT/source-diff.json" "$OUT/impact-report.json"
echo "== Output: $OUT"
