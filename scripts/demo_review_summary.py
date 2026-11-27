"""Print and check the outputs of scripts/demo-review.sh (stdlib only). Exit 1 on failure."""

import json
import sys
from collections import Counter
from pathlib import Path

out = Path(sys.argv[1])


def load(name: str):
    return json.loads((out / name).read_text(encoding="utf-8"))


problems: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        problems.append(message)


inv = load("inventory-sync.json")
print(
    f"\n[2] Inventory from {inv['source']}: {inv['systems']} systems, rulebook snapshot "
    f"{inv['rulebook']['snapshot']}"
)
for system, gaps in inv["data_gaps"].items():
    print(f"    data gap {system}: {', '.join(gaps)}")
for task in inv["data_gap_tasks"]:
    print(f"    data-gap task {task['number']} for {task['system_id']}: {task['action']}")
check(inv["systems"] == 9 and "SYS-009" in inv["data_gaps"], "inventory or data gap missing")

report = load("impact-report.json")
s = report["summary"]
print(
    f"\n[3] Impact report {report['report_id']}: {s['affected_controls']} controls, "
    f"{s['affected_systems']} systems, {s['findings_to_review']} findings to review"
)
for system in report["systems"]:
    print(
        f"    #{system['rank']} {system['system_id']} level {system['impact_level']:<3} "
        f"{system['findings_to_review']} findings"
    )
excluded = {e["system_id"]: e["reason"] for e in report["excluded_systems"]}
print(f"    excluded: {excluded}")

sync, again = load("task-sync.json"), load("task-sync-again.json")
print(
    f"\n[4] ServiceNow tasks: {Counter(t['action'] for t in sync['tasks'])}; "
    f"second run: {Counter(t['action'] for t in again['tasks'])}"
)
check(all(t["action"] == "created" for t in sync["tasks"]), "first sync should create")
check(all(t["action"] == "unchanged" for t in again["tasks"]), "second sync should be a no-op")

intake, queue = load("intake-result.json"), load("queue.json")
print(f"\n[5] Review desk: {intake['created']} placeholder findings; queue ({queue['ranking']}):")
for f in queue["findings"][:5]:
    print(
        f"    #{f['rank']} {f['system_id']} {f['impact_level']:<3} {f['control_id']:<10} "
        f"{f['verdict']} (confidence {f['confidence']}) due {f['due_date']}"
    )

plan = load("decision-plan.json")
print("\n[6] Decisions")
for i, item in enumerate(plan):
    result = load(f"decision-{i}-result.json")
    effects = {
        k: (v.get("number") or v.get("status") if isinstance(v, dict) and "status" in v else v)
        for k, v in result["side_effects"].items()
    }
    print(
        f"    log #{result['log']['seq']} {item['body']['action']:<24} {item['label']:<18} -> "
        f"{result['finding']['state']}; {effects}"
    )
    check(
        result["side_effects"].get("work-note") == "sent", f"work note not sent for {item['label']}"
    )
remediation = load("decision-0-result.json")["side_effects"]
check(remediation["remediation-task"]["status"] == "sent", "remediation task not sent")
check(
    load("decision-3-result.json")["side_effects"]["evidence-task"]["status"] == "sent",
    "evidence task not sent",
)

verify, checkpoint = load("verify.json"), load("checkpoint.json")
export_ok, tampered, truncated = (
    load("verify-export.json"),
    load("verify-tampered.json"),
    load("verify-truncated.json"),
)
print(
    f"\n[7] Decision log: {verify['records']} records, ok={verify['ok']}, "
    f"head #{checkpoint['head_seq']} {checkpoint['head_hash'][:23]}..."
)
print(
    f"    external checkpoints checked: {verify['checkpoints_checked']} "
    f"(sources: {verify['trusted_sources']})"
)
print(f"    exported copy:  ok={export_ok['ok']}")
print(f"    tampered copy:  ok={tampered['ok']}  {tampered['problems']}")
print(f"    truncated copy: ok={truncated['ok']}  {truncated['problems']}")
check(verify["ok"] and export_ok["ok"], "log should verify")
check(verify["checkpoints_checked"] > 0, "no external checkpoints were written")
check(not tampered["ok"] and "seq 2" in tampered["problems"][0], "tampering not detected")
check(
    not truncated["ok"] and truncated["problems"][-1].startswith("log ends at seq 3"),
    "truncation not detected with the checkpoint",
)

poam = load("poam.json")["plan-of-action-and-milestones"]
item = poam["poam-items"][0]
print(
    f"\n[8] POA&M {poam['metadata']['title']} v{poam['metadata']['version']} "
    f"({len(poam['poam-items'])} item):"
)
print("    " + json.dumps(item, indent=2).replace("\n", "\n    "))
risk = poam["risks"][0]
print(
    f"    risk deadline {risk['deadline']}; remediation: {risk['remediations'][0]['description']}"
)

fc = load("forecast.json")
print(
    f"\n    Forecast: {fc['findings']} findings x {fc['rate']['minutes_per_finding']} min "
    f"= {fc['reviewer_hours']} reviewer hours ({fc['rate']['source']})"
)
for t in fc["by_tenant"]:
    print(
        f"    {t['tenant']:<26} {t['findings']:>2} findings {t['reviewer_hours']:>4} h / "
        f"{t['capacity_hours_per_week']} h per week ({t['capacity_source']})"
    )
print(f"    staged rollout: {fc['staged_rollout']}")

tasks = load("servicenow-tasks.json")
types = Counter(t.get("u_govhub_type") for t in tasks)
notes = sum(len(t.get("work_notes", [])) for t in tasks if t.get("u_govhub_type") == "reassessment")
print(
    f"\n    ServiceNow (mock) u_govhub_task: {dict(types)}; "
    f"work notes on reassessment tasks: {notes}"
)
check(
    types
    == Counter(
        {"reassessment": len(sync["tasks"]), "data-gap": 1, "remediation": 1, "evidence-request": 1}
    ),
    f"unexpected task mix {dict(types)}",
)

if problems:
    print("\nDEMO CHECK FAILED: " + "; ".join(problems))
    sys.exit(1)
print("\nDemo checks passed.")
