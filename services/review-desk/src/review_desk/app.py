"""FastAPI application for the review desk.

Must only be reachable on localhost or the internal network until control-centre provides
real authentication: identity comes from placeholder headers (see identity.py).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from review_desk import decision_log, queue
from review_desk.db import get_session
from review_desk.decisions import DecisionError, DecisionRequest, decide, history
from review_desk.deps import AnyUser, AuthorizedReviewer, ReadSession, Tx
from review_desk.models import Finding, ReviewSession

RANKING = "impact level, verdict severity, uncertainty (lowest confidence first), due date"
app = FastAPI(title="Canadian AI Governance Hub - Review desk", version="0.1.0")


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
def ready(session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ready"}


@app.post("/intake/impact-report", tags=["findings"])
def intake(
    session: Tx,
    user: AuthorizedReviewer,
    report: Annotated[dict[str, Any], Body(description="A rulebook impact report")],
    servicenow: Annotated[
        dict[str, str] | None,
        Body(description="impact task_id -> ServiceNow task number (from the task sync)"),
    ] = None,
) -> dict[str, Any]:
    """Create one placeholder finding (unable-to-determine, no confidence) per affected
    system x control. Idempotent per report."""
    return queue.intake_report(session, report, servicenow)


@app.get("/queue", tags=["findings"])
def get_queue(
    session: ReadSession,
    user: AnyUser,
    tenant: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> dict[str, Any]:
    """Open findings ranked by impact level, verdict severity, uncertainty, due date."""
    ranked = queue.ranked_queue(session, tenant=tenant)
    return {
        "total": len(ranked),
        "ranking": RANKING,
        "findings": [queue.finding_view(f, i) for i, f in enumerate(ranked[:limit], start=1)],
    }


def _finding(session: Session, finding_id: str) -> Finding:
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(404, f"finding {finding_id} not found")
    return finding


@app.get("/findings/{finding_id}", tags=["findings"])
def get_finding(finding_id: str, session: ReadSession, user: AnyUser) -> dict[str, Any]:
    return queue.finding_view(_finding(session, finding_id))


@app.post("/findings/{finding_id}/open", tags=["findings"])
def open_finding(finding_id: str, session: Tx, reviewer: AuthorizedReviewer) -> dict[str, Any]:
    """Start a timed review. The decision measures time from here (server clock)."""
    _finding(session, finding_id)
    review = ReviewSession(
        finding_id=finding_id, reviewer=reviewer.id, opened_at=datetime.now(UTC), closed=False
    )
    session.add(review)
    session.flush()
    return {
        "session_id": review.id,
        "finding_id": finding_id,
        "opened_at": review.opened_at.isoformat(),
    }


@app.exception_handler(DecisionError)
def _decision_error(_request: Request, exc: DecisionError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


@app.post("/findings/{finding_id}/decisions", tags=["decisions"])
def post_decision(
    finding_id: str, request: DecisionRequest, session: Tx, reviewer: AuthorizedReviewer
) -> dict[str, Any]:
    """Record a human decision: accept, accept-with-remediation, reject,
    request-more-evidence or override-verdict. Appends one hash-chained log record."""
    finding = _finding(session, finding_id)
    row = decide(session, finding, request, reviewer)
    return {
        "finding": queue.finding_view(finding),
        "log": {"seq": row.seq, "record_hash": row.record_hash, "previous_hash": row.previous_hash},
    }


@app.get("/findings/{finding_id}/decisions", tags=["decisions"])
def get_decisions(finding_id: str, session: ReadSession, user: AnyUser) -> list[dict[str, Any]]:
    _finding(session, finding_id)
    return history(session, finding_id)


@app.get("/decision-log/verify", tags=["decision log"])
def verify_log(
    session: ReadSession,
    user: AnyUser,
    expect_seq: int | None = None,
    expect_head: str | None = None,
) -> dict[str, Any]:
    """Recompute every hash and link. With a checkpoint (seq + head hash) also detects
    records removed from the end."""
    return decision_log.verify_db(session, expect_seq=expect_seq, expect_head=expect_head).as_dict()


@app.get("/decision-log/export", tags=["decision log"], response_class=PlainTextResponse)
def export_log(session: ReadSession, user: AnyUser) -> str:
    """JSON Lines with the exact hashed text of every record (verify offline with
    ``review-desk verify-log --file``)."""
    return "\n".join(decision_log.export_lines(session)) + "\n"


@app.get("/decision-log/checkpoint", tags=["decision log"])
def get_checkpoint(session: ReadSession, user: AnyUser) -> dict[str, Any]:
    """Current head (seq, hash). Keep it outside the hub to detect truncation later."""
    return decision_log.checkpoint(session)
