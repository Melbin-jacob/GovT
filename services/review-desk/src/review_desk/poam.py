"""OSCAL 1.1.3 Plan of Action and Milestones (POA&M), one document per system.

Every accept-with-remediation decision adds one item. Each change stores a new, immutable
version of the system's POA&M (previous items are kept). Documents are normalized with
compliance-trestle and validated against the vendored NIST 1.1.3 POA&M schema.

Verdicts map to OSCAL as in the proposal's Appendix A.1 (our convention, to be confirmed
with GoC assessors):

| verdict             | target.status (reason)   | implementation-status |
|---------------------|--------------------------|-----------------------|
| met                 | satisfied (pass)         | implemented           |
| partially-met       | not-satisfied (fail)     | partial               |
| not-met             | not-satisfied (fail)     | planned               |
| not-applicable      | satisfied (other)        | not-applicable        |
| unable-to-determine | not-satisfied (other)    | (omitted)             |
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from govhub_shared import OSCAL_NS, OSCAL_VERSION
from govhub_shared.oscal import content_hash, normalize, stable_uuid, validate
from review_desk.models import Finding, PoamVersion

KIND: Final = "plan-of-action-and-milestones"
VERDICT_STATUS: dict[str, tuple[str, str, str | None]] = {
    "met": ("satisfied", "pass", "implemented"),
    "partially-met": ("not-satisfied", "fail", "partial"),
    "not-met": ("not-satisfied", "fail", "planned"),
    "not-applicable": ("satisfied", "other", "not-applicable"),
    "unable-to-determine": ("not-satisfied", "other", None),
}


def _prop(name: str, value: str) -> dict[str, str]:
    return {"name": name, "ns": OSCAL_NS, "value": value}


def _deadline(due: date) -> str:
    return f"{due.isoformat()}T23:59:59+00:00"


def item_uuid(finding_id: str, decision_uuid: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"govhub/poam-item/{finding_id}/{decision_uuid}"))


def latest(session: Session, system_id: str) -> PoamVersion | None:
    return session.scalars(
        select(PoamVersion)
        .where(PoamVersion.system_id == system_id)
        .order_by(PoamVersion.version.desc())
        .limit(1)
    ).first()


def add_item(
    session: Session,
    finding: Finding,
    *,
    decision_uuid: str,
    remediation_description: str,
    due_date: date,
    annotation: str,
    reviewer: str,
    decided_at: datetime,
    servicenow_task: str | None,
    log_seq_hint: int | None = None,
) -> tuple[PoamVersion, str]:
    """Store a new POA&M version for the finding's system with one more item."""
    previous = latest(session, finding.system_id)
    body: dict[str, Any] = (
        dict(previous.document[KIND])
        if previous
        else {
            "system-id": {"identifier-type": OSCAL_NS, "id": finding.system_id},
            "observations": [],
            "risks": [],
            "findings": [],
            "poam-items": [],
        }
    )
    body = {k: (list(v) if isinstance(v, list) else v) for k, v in body.items()}
    for key in ("observations", "risks", "findings", "poam-items"):
        body.setdefault(key, [])
    poam_item = item_uuid(finding.id, decision_uuid)
    observation = stable_uuid("poam-observation", poam_item)
    risk = stable_uuid("poam-risk", poam_item)
    response = stable_uuid("poam-remediation", poam_item)
    state, reason, implementation = VERDICT_STATUS[finding.verdict]
    collected = decided_at.isoformat()

    body["observations"].append(
        {
            "uuid": observation,
            "title": f"Review of {finding.control_id}",
            "description": annotation or "Accepted with remediation by a reviewer.",
            "methods": ["EXAMINE"],
            "collected": collected,
            "props": [_prop("reviewer", reviewer)],
        }
    )
    body["risks"].append(
        {
            "uuid": risk,
            "title": f"{finding.control_id} not fully met on {finding.system_id}",
            "description": finding.statement or finding.control_id,
            "statement": annotation or "See the remediation.",
            "status": "open",
            "deadline": _deadline(due_date),
            "remediations": [
                {
                    "uuid": response,
                    "lifecycle": "planned",
                    "title": f"Remediate {finding.control_id}",
                    "description": remediation_description,
                }
            ],
        }
    )
    target: dict[str, Any] = {
        "type": "statement-id",
        "target-id": f"{finding.control_id}_smt",
        "status": {"state": state, "reason": reason},
    }
    if implementation:
        target["implementation-status"] = {"state": implementation}
    finding_props = [_prop("verdict", finding.verdict)]
    if finding.confidence is not None:
        finding_props.append(_prop("confidence", f"{finding.confidence:.2f}"))
    if finding.placeholder:
        finding_props.append(_prop("placeholder-finding", "true"))
    body["findings"].append(
        {
            "uuid": finding.id,
            "title": f"{finding.control_id} on {finding.system_id}",
            "description": finding.statement or finding.control_id,
            "props": finding_props,
            "target": target,
            "related-observations": [{"observation-uuid": observation}],
            "related-risks": [{"risk-uuid": risk}],
        }
    )
    item_props = [
        _prop("control-id", finding.control_id),
        _prop("decision-uuid", decision_uuid),
        _prop("report-id", finding.report_id),
    ]
    if servicenow_task:
        item_props.append(_prop("servicenow-task", servicenow_task))
    body["poam-items"].append(
        {
            "uuid": poam_item,
            "title": f"Remediate {finding.control_id} on {finding.system_name}",
            "description": remediation_description,
            "props": item_props,
            "related-findings": [{"finding-uuid": finding.id}],
            "related-observations": [{"observation-uuid": observation}],
            "related-risks": [{"risk-uuid": risk}],
        }
    )
    version = (previous.version + 1) if previous else 1
    body["metadata"] = {
        "title": f"POA&M - {finding.system_name}",
        "last-modified": collected,
        "version": str(version),
        "oscal-version": OSCAL_VERSION,
        "props": [_prop("system-id", finding.system_id), _prop("tenant", finding.tenant)],
    }
    body["uuid"] = "00000000-0000-4000-8000-000000000000"
    doc = normalize({KIND: body}, KIND)
    doc[KIND]["uuid"] = stable_uuid("poam", finding.system_id, content_hash(doc, KIND))
    doc = normalize(doc, KIND)
    validate(doc, KIND)
    row = PoamVersion(
        system_id=finding.system_id,
        version=version,
        document=doc,
        content_hash=content_hash(doc, KIND),
    )
    session.add(row)
    session.flush()
    return row, poam_item
