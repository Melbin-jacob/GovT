"""Print and check the demo outputs (stdlib only). Exits 1 if an expectation fails."""

import json
import sys

diff_path, report_path = sys.argv[1], sys.argv[2]
with open(diff_path, encoding="utf-8") as fh:
    diff = json.load(fh)
with open(report_path, encoding="utf-8") as fh:
    report = json.load(fh)
problems = []

en = diff["en"]
print(
    f"\nClause diff ({diff['method']}; threshold {diff['threshold']}, "
    f"split {diff['split_threshold']})"
)
for pair in en["pairs"]:
    if pair["status"] != "unchanged":
        flags = ", ".join(pair["flags"])
        print(
            f"  {pair['old']:>6} -> {pair['new']:<6} {pair['status']:<19} "
            f"{pair['score']:<6} {flags}"
        )
for split in en["splits"]:
    print(f"  {split['old']:>6} -> {' + '.join(split['into'])}  split")
print(f"  added: {en['added']}  removed: {en['removed']}")
print(f"  EN/FR cross-check divergences: {len(diff['cross_check'])}")

if not any("renumbered" in p["flags"] for p in en["pairs"]):
    problems.append("no renumbered clause")
if not en["splits"]:
    problems.append("no split")
if not any("obligation-change" in p["flags"] for p in en["pairs"]):
    problems.append("no obligation change")

summary = report["summary"]
print(
    f"\nImpact report {report['report_id']}: {summary['affected_controls']} controls, "
    f"{summary['affected_systems']} systems, {summary['findings_to_review']} findings to review"
)
for system in report["systems"]:
    print(
        f"  #{system['rank']} {system['system_id']} level {system['impact_level']:<3} "
        f"{system['findings_to_review']} findings  {system['name']}"
    )
for task in report["tasks"]:
    print(
        f"  task {task['task_id']} P{task['priority']} due {task['due_date']} -> "
        f"{task['assigned_to']} ({task['due_date_basis']})"
    )
for item in report["maintenance"]:
    print(f"  maintenance: {item['kind']} {item.get('clause', '')}: {item['detail']}")

ranking = [s["system_id"] for s in report["systems"]]
if ranking[:2] != ["SYS-001", "SYS-002"]:
    problems.append(f"unexpected ranking {ranking}")
if len(report["tasks"]) != len(report["systems"]):
    problems.append("one task per affected system expected")

if problems:
    print("\nDEMO CHECK FAILED: " + "; ".join(problems))
    sys.exit(1)
print("\nDemo checks passed.")
