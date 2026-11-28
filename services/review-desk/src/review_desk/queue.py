"""Findings intake from impact reports, and the ranked review queue."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_desk.models import Finding

PLACEHOLDER_RATIONALE = (
    "Placeholder finding: the assessment engine does not exist yet "
    "(TODO(assessment-engine)). No automated verdict; a reviewer decides from the evidence."
)
IMPACT_RANK = {"unknown": 5, "IV": 4, "III": 3, "II": 2, "I": 1}
# Proposal: ranked by impact level, verdict severity and uncertainty.
VERDICT_SEVERITY = {
    "not-met": 4,
    "partially-met": 3,
    "unable-to-determine": 2,
    "met": 1,
    "not-applicable": 0,
}
OPEN_STATES = ("open", "awaiting-evidence")


def finding_id(report_id: str, system_id: str, control_id: str) -> str:
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"govhub/finding/{report_id}/{system_id}/{control_id}")
    )


def intake_report(
    session: Session, report: dict[str, Any], servicenow: dict[str, str] | None = None
) -> dict[str, Any]:
    """Create one placeholder finding per affected system x control. Idempotent."""
    report_id = str(report["report_id"])
    inputs = report.get("inputs", {})
    by_system = {s["system_id"]: s for s in report.get("systems", [])}
    created, existing = 0, 0
    for task in report.get("tasks", []):
        system = by_system.get(task["system_id"], {})
        for control in task.get("controls", []):
            fid = finding_id(report_id, task["system_id"], control["id"])
            if session.get(Finding, fid) is not None:
                existing += 1
                continue
            session.add(
                Finding(
                    id=fid,
                    report_id=report_id,
                    task_id=task["task_id"],
                    servicenow_task=(servicenow or {}).get(task["task_id"]),
                    system_id=task["system_id"],
                    system_name=system.get("name", task["system_id"]),
                    tenant=task["assignment_group"],
                    owner_email=task.get("assigned_to"),
                    impact_level=task["impact_level"],
                    catalog=inputs.get("catalog", ""),
                    catalog_version=inputs.get("catalog_version", ""),
                    control_id=control["id"],
                    statement=control.get("statement"),
                    evidence_requested=control.get("evidence_requested"),
                    reasons=list(control.get("reasons", [])),
                    obligation_change=bool(control.get("obligation_change")),
                    verdict="unable-to-determine",
                    confidence=None,
                    rationale=PLACEHOLDER_RATIONALE,
                    placeholder=True,
                    due_date=date.fromisoformat(task["due_date"]) if task.get("due_date") else None,
                    state="open",
                )
            )
            created += 1
    session.flush()
    return {"report_id": report_id, "created": created, "existing": existing}


def rank_key(f: Finding) -> tuple[Any, ...]:
    return (
        -IMPACT_RANK.get(f.impact_level, 0),
        -VERDICT_SEVERITY[f.verdict],
        f.confidence if f.confidence is not None else -1.0,  # no confidence = most uncertain
        f.due_date or date.max,
        f.system_id,
        f.control_id,
    )


def ranked_queue(
    session: Session,
    *,
    tenant: str | None = None,
    states: tuple[str, ...] = OPEN_STATES,
    tenants: frozenset[str] | None = None,
) -> list[Finding]:
    """``tenants``: only these (the caller's); None: every tenant."""
    query = select(Finding).where(Finding.state.in_(states))
    if tenant:
        query = query.where(Finding.tenant == tenant)
    if tenants is not None:
        query = query.where(Finding.tenant.in_(sorted(tenants)))
    return sorted(session.scalars(query), key=rank_key)


def finding_view(f: Finding, rank: int | None = None) -> dict[str, Any]:
    view = {
        "id": f.id,
        "rank": rank,
        "report_id": f.report_id,
        "system_id": f.system_id,
        "system_name": f.system_name,
        "tenant": f.tenant,
        "impact_level": f.impact_level,
        "control_id": f.control_id,
        "statement": f.statement,
        "evidence_requested": f.evidence_requested,
        "reasons": f.reasons,
        "obligation_change": f.obligation_change,
        "verdict": f.verdict,
        "confidence": f.confidence,
        "rationale": f.rationale,
        "placeholder": f.placeholder,
        "catalog": f.catalog,
        "catalog_version": f.catalog_version,
        "assessment": f.assessment,
        "due_date": f.due_date.isoformat() if f.due_date else None,
        "state": f.state,
        "task_id": f.task_id,
        "servicenow_task": f.servicenow_task,
    }
    if rank is None:
        view.pop("rank")
    return view
