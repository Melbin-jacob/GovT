#!/usr/bin/env bash
# Demo: rule change -> impact report -> ServiceNow tasks (MOCK) -> review decisions ->
# verified hash-chained log (and a tampered copy rejected) -> OSCAL POA&M -> forecast.
#
# SYNTHETIC/FICTIONAL data only. Needs `make up` (rulebook :8000, connector-hub :8001,
# review-desk :8002, mock ServiceNow :8003, all on localhost), curl and python3.
#
#   scripts/demo-review.sh [OUT_DIR]
set -euo pipefail

RULEBOOK="${RULEBOOK:-http://localhost:8000}"
CONNECTOR="${CONNECTOR:-http://127.0.0.1:8001}"
DESK="${DESK:-http://127.0.0.1:8002}"
MOCK="${MOCK:-http://127.0.0.1:8003}"
OUT="${1:-$(mktemp -d)}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WHO=(-H "X-GovHub-User: governance-officer-01" -H "X-GovHub-Role: governance-officer")
mkdir -p "$OUT"

# shellcheck source=lib/hub-token.sh
. "$ROOT/scripts/lib/hub-token.sh"
hub_tokens
auth() { hub_auth "$1" "$2"; }
call() {  # call METHOD URL [BODY_FILE] -> stdout (fails on HTTP errors)
  if [ $# -ge 3 ]; then
    curl --fail-with-body -sS -X "$1" "$2" "${WHO[@]}" -H "$(auth "$1" "$2")" -H 'content-type: application/json' --data-binary "@$3"
  else
    curl --fail-with-body -sS -X "$1" "$2" "${WHO[@]}" -H "$(auth "$1" "$2")"
  fi
}
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

echo "== 0. Fresh mock ServiceNow (fictional seed)"
curl --fail -sS -X POST "$MOCK/__mock/reset" >/dev/null

echo "== 1. Rulebook: synthetic sources, linked catalogs, profiles"
for f in "$ROOT"/data/demo/sources/example-widgets.*.json; do
  case "$f" in *.meta.json) continue ;; esac
  call POST "$RULEBOOK/sources" "$f" >/dev/null
done
for lang in en fr; do call POST "$RULEBOOK/catalogs" "$ROOT/data/demo/catalogs/example-widgets.$lang.json" >/dev/null; done
for f in "$ROOT"/data/profiles/*.json "$ROOT"/data/demo/profiles/*.json; do
  call PUT "$RULEBOOK/profiles/$(basename "$f" .json)" "$f" >/dev/null
done

echo "== 2. Inventory from ServiceNow (mock) -> rulebook, with data-gap tasks"
call POST "$CONNECTOR/inventory/sync" > "$OUT/inventory-sync.json"

echo "== 3. Impact report (source change 2023-01-01 -> 2025-01-01)"
cat > "$OUT/impact-request.json" <<JSON
{"catalog": "example-widgets", "catalog_version": "1.0.0",
 "source": {"instrument": "example-widgets", "from": "2023-01-01", "to": "2025-01-01"},
 "as_of": "2026-12-01"}
JSON
call POST "$RULEBOOK/impact-reports" "$OUT/impact-request.json" > "$OUT/impact-report.json"

echo "== 4. Reassessment tasks -> ServiceNow u_govhub_task (twice: second run is idempotent)"
call POST "$CONNECTOR/tasks/sync-impact-report" "$OUT/impact-report.json" > "$OUT/task-sync.json"
call POST "$CONNECTOR/tasks/sync-impact-report" "$OUT/impact-report.json" > "$OUT/task-sync-again.json"

echo "== 5. Findings into the review desk (placeholder verdicts), ranked queue"
python3 - "$OUT" <<'PY'
import json, sys
out = sys.argv[1]
report = json.load(open(f"{out}/impact-report.json"))
sync = json.load(open(f"{out}/task-sync.json"))
mapping = {t["task_id"]: t["number"] for t in sync["tasks"]}
json.dump({"report": report, "servicenow": mapping}, open(f"{out}/intake.json", "w"))
PY
call POST "$DESK/intake/impact-report" "$OUT/intake.json" > "$OUT/intake-result.json"
call GET "$DESK/queue?limit=1000" > "$OUT/queue.json"

echo "== 6. Human decisions (timed): one of each action"
python3 - "$OUT" <<'PY'
import json, sys
out = sys.argv[1]
q = json.load(open(f"{out}/queue.json"))["findings"]
plan = [
    (q[0], {"action": "accept-with-remediation",
            "annotation": "Register lacks the firmware version required by the new clause.",
            "remediation": {"description": "Add the firmware version to every widget register entry.",
                            "due_date": "2027-01-31"}}),
    (q[1], {"action": "accept", "annotation": "Calibration evidence reviewed; acceptable."}),
    (q[2], {"action": "reject", "annotation": "Control does not apply: the system logs no calibrations."}),
    (q[3], {"action": "request-more-evidence", "annotation": "Attach the 2026 calibration log."}),
    (q[4], {"action": "override-verdict", "verdict": "partially-met",
            "annotation": "Notices exist online only; telephone channel missing."}),
]
json.dump([{"finding": f["id"], "label": f"{f['system_id']} {f['control_id']}", "body": b} for f, b in plan],
          open(f"{out}/decision-plan.json", "w"), indent=1)
PY
n=$(python3 -c "import json; print(len(json.load(open('$OUT/decision-plan.json'))))")
for i in $(seq 0 $((n - 1))); do
  fid=$(python3 -c "import json; print(json.load(open('$OUT/decision-plan.json'))[$i]['finding'])")
  sid=$(call POST "$DESK/findings/$fid/open" | json "d['session_id']")
  python3 -c "import json; p=json.load(open('$OUT/decision-plan.json'))[$i]; b=p['body']; b['session_id']=$sid; json.dump(b, open('$OUT/decision-$i.json','w'))"
  call POST "$DESK/findings/$fid/decisions" "$OUT/decision-$i.json" > "$OUT/decision-$i-result.json"
done

echo "== 7. Verify the decision log; export; tamper with a copy; verify again"
call GET "$DESK/decision-log/verify?trust=file&trust=servicenow" > "$OUT/verify.json"
call GET "$DESK/decision-log/checkpoint" > "$OUT/checkpoint.json"
call GET "$DESK/decision-log/export" > "$OUT/decision-log.jsonl"
python3 - "$OUT" <<'PY'
import sys
out = sys.argv[1]
lines = open(f"{out}/decision-log.jsonl", encoding="utf-8").read().splitlines()
tampered = list(lines)
tampered[1] = tampered[1].replace("acceptable", "excellent")  # a quiet edit to decision #2
open(f"{out}/decision-log.tampered.jsonl", "w", encoding="utf-8").write("\n".join(tampered) + "\n")
# Drop the last two records: the chain itself still verifies; only the checkpoint notices.
open(f"{out}/decision-log.truncated.jsonl", "w", encoding="utf-8").write("\n".join(lines[:3]) + "\n")
PY
curl --fail -sS -X POST "$DESK/decision-log/verify-export" -H "$(auth POST "$DESK/decision-log/")" --data-binary "@$OUT/decision-log.jsonl" > "$OUT/verify-export.json"
curl --fail -sS -X POST "$DESK/decision-log/verify-export" -H "$(auth POST "$DESK/decision-log/")" --data-binary "@$OUT/decision-log.tampered.jsonl" > "$OUT/verify-tampered.json"
seq_head=$(json "d['head_seq']" < "$OUT/checkpoint.json"); hash_head=$(json "d['head_hash']" < "$OUT/checkpoint.json")
curl --fail -sS -X POST "$DESK/decision-log/verify-export?expect_seq=$seq_head&expect_head=$hash_head" -H "$(auth POST "$DESK/decision-log/")" \
  --data-binary "@$OUT/decision-log.truncated.jsonl" > "$OUT/verify-truncated.json"

echo "== 8. OSCAL POA&M, forecast, ServiceNow state"
sys_id=$(python3 -c "import json; print(json.load(open('$OUT/queue.json'))['findings'][0]['system_id'])")
call GET "$DESK/poam/$sys_id" > "$OUT/poam.json"
call POST "$DESK/forecast" "$OUT/impact-report.json" > "$OUT/forecast.json"
curl --fail -sS "$MOCK/__mock/tables/u_govhub_task" > "$OUT/servicenow-tasks.json"

python3 "$ROOT/scripts/demo_review_summary.py" "$OUT"
echo "== Output: $OUT"
