"""Summary and checks for scripts/demo-assessment.sh (fails if a check fails)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
problems: list[str] = []


def load(name: str) -> dict:  # type: ignore[type-arg]
    return json.loads((out / name).read_text("utf-8"))  # type: ignore[no-any-return]


def check(ok: bool, message: str) -> None:
    if not ok:
        problems.append(message)


upload = load("upload-sys003.json")
print(
    f"[2] evidence {upload['filename']}: {upload['passages']} passage(s), "
    f"flagged {upload['flagged_passages']}, encrypted={upload['encrypted']}"
)
check(bool(upload["flagged_passages"]), "the injected instruction was not flagged")
check(upload["encrypted"] is True, "evidence should be encrypted with the dev key")

runs = load("assess-sys003.json")["runs"]
print("[3] SYS-003 drafts:")
for run in runs:
    for a in run["assessments"]:
        d = a["detail"]
        print(
            f"    {a['control_id']:10} {a['method']:5} -> {a['verdict']:20} "
            f"model said {d.get('model_verdict') or '-':14} "
            f"reason {d.get('downgrade_reason') or '-'}"
        )
    print(f"    review desk: {run['review_desk']}")
    check(all(v == "sent" for v in run["review_desk"].values()), "drafts not sent to review desk")
register = next(a for r in runs for a in r["assessments"] if a["control_id"] == "WID-6.3.2")
check(register["verdict"] == "unable-to-determine", "injection must not yield met")
check(register["detail"]["model_verdict"] == "met", "the scripted model says met")
check(
    register["detail"]["downgrade_reason"] in ("flagged-support", "flagged-in-context"),
    "expected the flagged-evidence safeguard",
)

sys005 = load("assess-sys005.json")["assessments"][0]
print(
    f"[4] SYS-005 WID-6.4.1 -> {sys005['verdict']} (confidence {sys005['confidence']}, "
    f"{sys005['detail']['confidence_source']}); quote: {sys005['detail']['cited_quote']!r}"
)
check(sys005["verdict"] == "partially-met", "expected partially-met for online-only notice")
doc = load("assessment-results-sys005.json")
finding = doc["assessment-results"]["results"][0]["findings"][0]
print("    OSCAL finding:", json.dumps(finding, ensure_ascii=False)[:300], "...")

queue = load("queue-after.json")["findings"]
assessed = [f for f in queue if f["system_id"] == "SYS-003"]
print(
    f"[5] SYS-003 in the queue: {[(f['control_id'], f['verdict'], f['state']) for f in assessed]}"
)
check(all(f["state"] in ("open", "awaiting-evidence") for f in assessed), "engine closed a finding")
check(all(not f["placeholder"] for f in assessed), "placeholders should be replaced")

if problems:
    print("\nDEMO CHECKS FAILED:\n- " + "\n- ".join(problems))
    sys.exit(1)
print("\nDemo checks passed.")
