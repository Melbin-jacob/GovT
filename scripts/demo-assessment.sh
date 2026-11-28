#!/usr/bin/env bash
# Demo: the assessment engine drafts verdicts; a person still decides.
#
# SYNTHETIC/FICTIONAL data only, run after scripts/demo-review.sh against `make up`
# (assessment engine :8005, review desk :8002, all on localhost). The model is the
# SCRIPTED FAKE model in Compose (recorded replies), reached through the engine's real
# HTTP gateway and host allowlist: no real model runs.
#
#   scripts/demo-assessment.sh [OUT_DIR]
set -euo pipefail

ENGINE="${ENGINE:-http://127.0.0.1:8005}"
DESK="${DESK:-http://127.0.0.1:8002}"
OUT="${1:-$(mktemp -d)}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVIDENCE="$ROOT/data/accuracy/synthetic-demo/evidence"
mkdir -p "$OUT"

# shellcheck source=lib/hub-token.sh
. "$ROOT/scripts/lib/hub-token.sh"
hub_tokens
call() {  # call METHOD URL [BODY_FILE]
  if [ $# -ge 3 ]; then
    curl --fail-with-body -sS -X "$1" "$2" -H "$(hub_auth "$1" "$2")" -H 'content-type: application/json' --data-binary "@$3"
  else
    curl --fail-with-body -sS -X "$1" "$2" -H "$(hub_auth "$1" "$2")"
  fi
}
upload() { curl --fail-with-body -sS -H "$(hub_auth POST "$ENGINE/systems/$1/evidence")" -F "file=@$2" "$ENGINE/systems/$1/evidence"; }

echo "== 1. Facts for SYS-003's rule-based checks (fictional)"
cat > "$OUT/facts.json" <<JSON
{"facts": {"calibration_log_months": {"value": 30, "source": "calibration log export"},
           "last_annual_report_date": {"value": "2026-04-01", "source": "annual report"}}}
JSON
call PUT "$ENGINE/systems/SYS-003/facts" "$OUT/facts.json" > "$OUT/facts-result.json"

echo "== 2. Evidence for SYS-003 (register published, with an injected instruction)"
upload SYS-003 "$EVIDENCE/en-register-published-injected.txt" > "$OUT/upload-sys003.json"

echo "== 3. Assess SYS-003's open findings; drafts go to the review desk"
echo '{"as_of": "2026-12-01"}' > "$OUT/as-of.json"
call POST "$ENGINE/systems/SYS-003/assess-open-findings" "$OUT/as-of.json" > "$OUT/assess-sys003.json"

echo "== 4. A judgment check without the injection: SYS-005, notice on one channel only"
upload SYS-005 "$EVIDENCE/en-notice-online-only.txt" > "$OUT/upload-sys005.json"
cat > "$OUT/run-sys005.json" <<JSON
{"system_id": "SYS-005", "catalog": "example-widgets", "catalog_version": "1.0.0",
 "control_ids": ["WID-6.4.1"], "as_of": "2026-12-01"}
JSON
call POST "$ENGINE/assessments" "$OUT/run-sys005.json" > "$OUT/assess-sys005.json"
run_id=$(python3 -c "import json; print(json.load(open('$OUT/assess-sys005.json'))['run_id'])")
call GET "$ENGINE/runs/$run_id/assessment-results" > "$OUT/assessment-results-sys005.json"

echo "== 5. Review queue after the engine (findings still open)"
call GET "$DESK/queue?limit=1000" > "$OUT/queue-after.json"

python3 "$ROOT/scripts/demo_assessment_summary.py" "$OUT"
echo "== Output: $OUT"
