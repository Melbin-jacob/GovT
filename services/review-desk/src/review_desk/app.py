"""FastAPI application for the review desk.

Must only be reachable on localhost or the internal network until control-centre provides
real authentication: identity comes from placeholder headers (see identity.py).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from review_desk import checkpoints, decision_log, forecast, queue
from review_desk.config import get_settings
from review_desk.db import get_session
from review_desk.decisions import DecisionError, DecisionRequest, decide, history
from review_desk.deps import AnyUser, AuthorizedReviewer, ReadSession, Tx
from review_desk.models import Finding, PoamVersion, ReviewSession
from review_desk.tasks import HttpTaskSink, NullTaskSink, TaskSink

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


def get_task_sink() -> TaskSink:
    """connector-hub over the internal network, or a null sink (overridden in tests)."""
    url = get_settings().connector_hub_url
    return HttpTaskSink(url) if url else NullTaskSink()


Sink = Annotated[TaskSink, Depends(get_task_sink)]


@app.post("/findings/{finding_id}/decisions", tags=["decisions"])
def post_decision(
    finding_id: str,
    request: DecisionRequest,
    session: Tx,
    reviewer: AuthorizedReviewer,
    sink: Sink,
) -> dict[str, Any]:
    """Record a human decision: accept, accept-with-remediation, reject,
    request-more-evidence or override-verdict. Performs the side effects (POA&M item,
    ServiceNow tasks through connector-hub) and appends one hash-chained log record."""
    finding = _finding(session, finding_id)
    row = decide(session, finding, request, reviewer, sink=sink)
    record = json.loads(row.record_text)
    session.commit()  # the checkpoint must describe a committed log
    settings = get_settings()
    checkpoint = checkpoints.write(
        seq=row.seq,
        head_hash=row.record_hash,
        every=settings.checkpoint_every,
        file_path=settings.checkpoint_file,
        sink=sink,
        task_correlation_id=finding.task_id,
    )
    return {
        "finding": queue.finding_view(finding),
        "side_effects": record["side-effects"],
        "log": {"seq": row.seq, "record_hash": row.record_hash, "previous_hash": row.previous_hash},
        "checkpoint": checkpoint,
    }


@app.get("/poam", tags=["poam"])
def list_poams(session: ReadSession, user: AnyUser) -> list[dict[str, Any]]:
    rows = session.scalars(select(PoamVersion).order_by(PoamVersion.system_id, PoamVersion.version))
    latest: dict[str, PoamVersion] = {r.system_id: r for r in rows}
    return [
        {
            "system_id": r.system_id,
            "version": r.version,
            "items": len(r.document["plan-of-action-and-milestones"]["poam-items"]),
        }
        for r in latest.values()
    ]


@app.get("/poam/{system_id}", tags=["poam"])
def get_poam(
    system_id: str, session: ReadSession, user: AnyUser, version: int | None = None
) -> dict[str, Any]:
    """The system's OSCAL 1.1.3 POA&M (latest version unless ``version`` is given)."""
    query = select(PoamVersion).where(PoamVersion.system_id == system_id)
    if version is not None:
        query = query.where(PoamVersion.version == version)
    row = session.scalars(query.order_by(PoamVersion.version.desc()).limit(1)).first()
    if row is None:
        raise HTTPException(404, f"no POA&M for {system_id}")
    return row.document


@app.get("/findings/{finding_id}/decisions", tags=["decisions"])
def get_decisions(finding_id: str, session: ReadSession, user: AnyUser) -> list[dict[str, Any]]:
    _finding(session, finding_id)
    return history(session, finding_id)


def trusted_checkpoints(
    trust: list[str], sink: TaskSink
) -> tuple[list[decision_log.Checkpoint], dict[str, Any]]:
    """Checkpoints from the external sources named in ``trust`` (file, servicenow)."""
    from pathlib import Path

    found: list[decision_log.Checkpoint] = []
    sources: dict[str, Any] = {}
    if "file" in trust:
        path = get_settings().checkpoint_file
        from_file = checkpoints.read_file(Path(path)) if path else []
        sources["file"] = {"path": path, "checkpoints": len(from_file)}
        found += from_file
    if "servicenow" in trust:
        notes = sink.task_notes()
        from_sn = checkpoints.parse_notes(notes or [])
        sources["servicenow"] = {
            "available": notes is not None,
            "checkpoints": len(from_sn),
        }
        found += from_sn
    return found, sources


TrustQ = Annotated[
    list[str],
    Query(description="External checkpoint sources to trust: file, servicenow"),
]


@app.get("/decision-log/verify", tags=["decision log"])
def verify_log(
    session: ReadSession,
    user: AnyUser,
    sink: Sink,
    trust: TrustQ = [],  # noqa: B006 - FastAPI query default
    expect_seq: int | None = None,
    expect_head: str | None = None,
) -> dict[str, Any]:
    """Recompute every hash and link. Checkpoints from the trusted external sources (or a
    given seq + head hash) must still match, which detects records removed from the end."""
    unknown = sorted(set(trust) - {"file", "servicenow"})
    if unknown:
        raise HTTPException(422, f"unknown trust source(s) {unknown}; use file, servicenow")
    found, sources = trusted_checkpoints(trust, sink)
    result = decision_log.verify_db(
        session, expect_seq=expect_seq, expect_head=expect_head, checkpoints=found
    ).as_dict()
    return {**result, "trusted_sources": sources}


@app.get("/decision-log/checkpoint-status", tags=["decision log"])
def checkpoint_status(session: ReadSession, user: AnyUser, sink: Sink) -> dict[str, Any]:
    """Latest external checkpoint from each source, compared with the database head."""
    head = decision_log.checkpoint(session)
    out: dict[str, Any] = {"database_head": head, "every": get_settings().checkpoint_every}
    for source in ("file", "servicenow"):
        found, info = trusted_checkpoints([source], sink)
        latest = max(found, key=lambda c: c.seq, default=None)
        out[source] = {
            **info[source],
            "latest_seq": latest.seq if latest else None,
            "latest_hash": latest.head_hash if latest else None,
            "behind_database": head["head_seq"] - latest.seq if latest else None,
        }
    return out


@app.get("/decision-log/export", tags=["decision log"], response_class=PlainTextResponse)
def export_log(session: ReadSession, user: AnyUser) -> str:
    """JSON Lines with the exact hashed text of every record (verify offline with
    ``review-desk verify-log --file``)."""
    return "\n".join(decision_log.export_lines(session)) + "\n"


@app.post("/decision-log/verify-export", tags=["decision log"])
async def verify_export(
    request: Request,
    user: AnyUser,
    expect_seq: int | None = None,
    expect_head: str | None = None,
) -> dict[str, Any]:
    """Verify an exported JSON Lines file sent as the request body (same check as
    ``review-desk verify-log --file``). Nothing is stored."""
    body = (await request.body()).decode("utf-8")
    try:
        entries = decision_log.file_entries(body.splitlines())
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"not a decision-log export: {exc}") from exc
    return decision_log.verify_entries(
        entries, expect_seq=expect_seq, expect_head=expect_head
    ).as_dict()


@app.get("/decision-log/checkpoint", tags=["decision log"])
def get_checkpoint(session: ReadSession, user: AnyUser) -> dict[str, Any]:
    """Current head (seq, hash). Keep it outside the hub to detect truncation later."""
    return decision_log.checkpoint(session)


def _rate_config() -> forecast.RateConfig:
    from pathlib import Path

    return forecast.load_rate_config(Path(get_settings().review_rate_path))


@app.post("/forecast", tags=["forecast"])
def forecast_report(
    session: ReadSession,
    user: AnyUser,
    report: Annotated[dict[str, Any], Body(description="A rulebook impact report")],
) -> dict[str, Any]:
    """Reviewer hours an impact report will need, per tenant, against weekly capacity."""
    return forecast.from_report(session, _rate_config(), report)


@app.get("/forecast", tags=["forecast"])
def forecast_queue(session: ReadSession, user: AnyUser) -> dict[str, Any]:
    """Reviewer hours for the open review queue."""
    return forecast.from_queue(session, _rate_config())
