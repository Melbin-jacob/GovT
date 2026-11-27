"""Reviewer decisions: validation, finding state changes, and the log record.

Actions (proposal: reviewers accept, reject, change or annotate findings):

| action                   | requires                         | finding state afterwards    |
|--------------------------|----------------------------------|-----------------------------|
| accept                   | -                                | accepted                    |
| accept-with-remediation  | remediation description + due    | accepted-with-remediation   |
| reject                   | annotation (the reason)          | rejected                    |
| request-more-evidence    | annotation (what is needed)      | awaiting-evidence           |
| override-verdict         | new verdict + annotation         | overridden                  |

Only open or awaiting-evidence findings can be decided. Side effects (POA&M item,
ServiceNow tasks) are performed by the caller and recorded in the same log record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from review_desk import decision_log, poam
from review_desk.identity import Reviewer
from review_desk.models import VERDICTS, DecisionRecord, Finding, ReviewSession
from review_desk.queue import OPEN_STATES
from review_desk.tasks import NullTaskSink, TaskSink

Action = Literal[
    "accept", "accept-with-remediation", "reject", "request-more-evidence", "override-verdict"
]
Verdict = Literal["met", "partially-met", "not-met", "not-applicable", "unable-to-determine"]
NEXT_STATE: dict[str, str] = {
    "accept": "accepted",
    "accept-with-remediation": "accepted-with-remediation",
    "reject": "rejected",
    "request-more-evidence": "awaiting-evidence",
    "override-verdict": "overridden",
}


class Remediation(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    due_date: date


class DecisionRequest(BaseModel):
    action: Action
    annotation: str = Field(default="", max_length=4000)
    verdict: Verdict | None = None
    remediation: Remediation | None = None
    session_id: int | None = None

    @model_validator(mode="after")
    def _check(self) -> DecisionRequest:
        if (
            self.action in ("reject", "request-more-evidence", "override-verdict")
            and not self.annotation.strip()
        ):
            raise ValueError(f"{self.action} needs an annotation (the reason)")
        if self.action == "override-verdict" and self.verdict is None:
            raise ValueError("override-verdict needs the new verdict")
        if self.action != "override-verdict" and self.verdict is not None:
            raise ValueError("only override-verdict changes the verdict")
        if (self.action == "accept-with-remediation") != (self.remediation is not None):
            raise ValueError("remediation is required for, and only for, accept-with-remediation")
        return self


class DecisionError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


def _review_seconds(
    session: Session, finding: Finding, reviewer: Reviewer, session_id: int | None, now: datetime
) -> float | None:
    query = select(ReviewSession).where(
        ReviewSession.finding_id == finding.id,
        ReviewSession.reviewer == reviewer.id,
        ReviewSession.closed.is_(False),
    )
    if session_id is not None:
        query = query.where(ReviewSession.id == session_id)
    review = session.scalars(query.order_by(ReviewSession.id.desc())).first()
    if review is None:
        if session_id is not None:
            raise DecisionError(409, f"review session {session_id} is not open for this reviewer")
        return None
    review.closed = True
    return round(max((now - review.opened_at).total_seconds(), 0.0), 3)


def decide(
    session: Session,
    finding: Finding,
    request: DecisionRequest,
    reviewer: Reviewer,
    *,
    sink: TaskSink | None = None,
    now: datetime | None = None,
) -> DecisionRecord:
    """Apply the decision, perform its side effects (POA&M item, ServiceNow tasks through
    connector-hub) and append one log record with their outcomes, in the caller's
    transaction."""
    if finding.state not in OPEN_STATES:
        raise DecisionError(409, f"finding is already {finding.state}")
    now = now or datetime.now(UTC)
    verdict_before = finding.verdict
    verdict_after = request.verdict if request.action == "override-verdict" else verdict_before
    if request.action == "override-verdict" and verdict_after == verdict_before:
        raise DecisionError(422, f"verdict is already {verdict_before}")
    assert verdict_after in VERDICTS  # noqa: S101 - enforced by the request model
    record: dict[str, Any] = {
        "uuid": str(uuid.uuid4()),
        "finding-uuid": finding.id,
        "report-id": finding.report_id,
        "control-id": finding.control_id,
        "system-id": finding.system_id,
        "tenant": finding.tenant,
        "action": request.action,
        "verdict-before": verdict_before,
        "verdict-after": verdict_after,
        "confidence-at-review": finding.confidence,
        "placeholder-finding": finding.placeholder,
        **(
            {"assessment-id": finding.assessment.get("assessment_id")} if finding.assessment else {}
        ),
        "reviewer": reviewer.as_record(),
        "timestamp": now.isoformat(),
        "annotation": request.annotation,
        "review-seconds": _review_seconds(session, finding, reviewer, request.session_id, now),
    }
    if request.remediation is not None:
        record["remediation"] = request.remediation.model_dump(mode="json")
    record["side-effects"] = _side_effects(
        session, finding, request, reviewer, record, sink or NullTaskSink(), now
    )
    finding.verdict = verdict_after
    finding.state = NEXT_STATE[request.action]
    return decision_log.append(session, record)


PRIORITY = {"IV": 1, "unknown": 1, "III": 2, "II": 3, "I": 4}


def _side_effects(
    session: Session,
    finding: Finding,
    request: DecisionRequest,
    reviewer: Reviewer,
    record: dict[str, Any],
    sink: TaskSink,
    now: datetime,
) -> dict[str, Any]:
    effects: dict[str, Any] = {}
    common = {
        "tenant": finding.tenant,
        "owner_email": finding.owner_email,
        "system_id": finding.system_id,
        "priority": PRIORITY.get(finding.impact_level, 3),
    }
    if request.action == "accept-with-remediation":
        assert request.remediation is not None  # noqa: S101 - validated
        item = poam.item_uuid(finding.id, record["uuid"])
        task = sink.upsert(
            {
                **common,
                "correlation_id": f"POAM-{item}",
                "type": "remediation",
                "short_description": (f"Remediate {finding.control_id} on {finding.system_name}")[
                    :160
                ],
                "description": (
                    f"{request.remediation.description}\n\nReviewer note: "
                    f"{request.annotation or '-'}\nPOA&M item: {item}"
                ),
                "due_date": request.remediation.due_date.isoformat(),
                "reference": item,
                "note": f"Accepted with remediation by {reviewer.id}",
            }
        )
        version, item_id = poam.add_item(
            session,
            finding,
            decision_uuid=record["uuid"],
            remediation_description=request.remediation.description,
            due_date=request.remediation.due_date,
            annotation=request.annotation,
            reviewer=reviewer.id,
            decided_at=now,
            servicenow_task=task.get("number"),
        )
        effects["poam"] = {
            "system-id": finding.system_id,
            "version": version.version,
            "item-uuid": item_id,
            "document-hash": version.content_hash,
        }
        effects["remediation-task"] = _task_outcome(task)
    if request.action == "request-more-evidence":
        task = sink.upsert(
            {
                **common,
                "correlation_id": f"EVID-{finding.id}",
                "type": "evidence-request",
                "short_description": (
                    f"Provide evidence for {finding.control_id} ({finding.system_name})"
                )[:160],
                "description": (
                    f"{request.annotation}\n\nEvidence that would satisfy it: "
                    f"{finding.evidence_requested or '-'}"
                ),
                "due_date": finding.due_date.isoformat() if finding.due_date else None,
                "reference": finding.id,
                "note": f"Evidence requested by {reviewer.id}",
            }
        )
        effects["evidence-task"] = _task_outcome(task)
    if finding.task_id:
        note = sink.note(
            finding.task_id,
            f"{finding.control_id}: {request.action} by {reviewer.id} "
            f"(verdict {record['verdict-after']}). {request.annotation}".strip(),
        )
        effects["work-note"] = note.get("status", "sent")
    return effects


def _task_outcome(task: dict[str, Any]) -> dict[str, Any]:
    if task.get("status") != "sent":
        return {"status": task.get("status", "not sent")}
    return {"status": "sent", "number": task.get("number"), "action": task.get("action")}


def history(session: Session, finding_id: str) -> list[dict[str, Any]]:
    import json

    rows = session.scalars(
        select(DecisionRecord)
        .where(DecisionRecord.finding_id == finding_id)
        .order_by(DecisionRecord.seq)
    )
    return [{**json.loads(r.record_text), "record-hash": r.record_hash} for r in rows]
