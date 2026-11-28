"""FastAPI application for the review desk.

Callers present internal tokens (``govhub_shared.auth``); every request's database
session is bound to the caller's tenants (row-level security, ``govhub_shared.tenancy``).
The few platform-wide reads widen that scope explicitly below (``tenancy.widened``).
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

from govhub_shared import tenancy
from govhub_shared.auth import GOVERNANCE_OFFICER, Principal
from govhub_shared.auth.client import trust_store
from govhub_shared.auth.web import install
from review_desk import assessments, checkpoints, decision_log, forecast, provenance, queue
from review_desk.config import get_settings
from review_desk.db import get_session
from review_desk.decisions import DecisionError, DecisionRequest, decide, history
from review_desk.deps import (
    EngineOnly,
    ForecastReader,
    IntakeCaller,
    LogExporter,
    LogReader,
    ReadSession,
    ReviewerAnywhere,
    TenantReader,
    Tx,
)
from review_desk.identity import reviewer_in, visible_tenants
from review_desk.models import Finding, PoamVersion, ReviewSession
from review_desk.tasks import HttpTaskSink, NullTaskSink, TaskSink

RANKING = "impact level, verdict severity, uncertainty (lowest confidence first), due date"
app = FastAPI(title="Canadian AI Governance Hub - Review desk", version="0.1.0")


# Internal tokens (GOVHUB_TRUST_FILE); without them protected endpoints answer 503.
_trust = trust_store()
if _trust is not None:
    install(app, "review-desk", _trust)


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
    user: IntakeCaller,
    report: Annotated[dict[str, Any], Body(description="A rulebook impact report")],
    servicenow: Annotated[
        dict[str, str] | None,
        Body(description="impact task_id -> ServiceNow task number (from the task sync)"),
    ] = None,
) -> dict[str, Any]:
    """Create one placeholder finding (unable-to-determine, no confidence) per affected
    system x control. Idempotent per report. Intake is platform-wide (a governance
    officer or the hub's own services), so it reads and writes across tenants."""
    with tenancy.widened(session, tenancy.ALL_TENANTS):
        return queue.intake_report(session, report, servicenow)


@app.get("/queue", tags=["findings"])
def get_queue(
    session: ReadSession,
    user: TenantReader,
    tenant: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> dict[str, Any]:
    """Open findings ranked by impact level, verdict severity, uncertainty, due date."""
    ranked = queue.ranked_queue(session, tenant=tenant, tenants=visible_tenants(user))
    return {
        "total": len(ranked),
        "ranking": RANKING,
        "findings": [queue.finding_view(f, i) for i, f in enumerate(ranked[:limit], start=1)],
    }


def _finding(session: Session, finding_id: str, who: Principal | None = None) -> Finding:
    """The finding, if the caller may see its tenant (another tenant's: "not found")."""
    finding = session.get(Finding, finding_id)
    visible = visible_tenants(who) if who is not None else None
    if finding is None or (visible is not None and finding.tenant not in visible):
        raise HTTPException(404, f"finding {finding_id} not found")
    return finding


@app.get("/findings/{finding_id}", tags=["findings"])
def get_finding(finding_id: str, session: ReadSession, user: TenantReader) -> dict[str, Any]:
    return queue.finding_view(_finding(session, finding_id, user))


@app.put("/findings/{finding_id}/assessment", tags=["findings"])
def put_assessment(
    finding_id: str,
    result: assessments.AssessmentResult,
    session: Tx,
    user: EngineOnly,
) -> dict[str, Any]:
    """The assessment engine's draft replaces the placeholder (the engine's service
    identity only). The finding stays open: a person decides."""
    finding = _finding(session, finding_id)
    try:
        assessments.apply(session, finding, result)
    except assessments.AssessmentRefusedError as exc:
        raise HTTPException(409, str(exc)) from exc
    return queue.finding_view(finding)


@app.post("/findings/{finding_id}/open", tags=["findings"])
def open_finding(finding_id: str, session: Tx, who: ReviewerAnywhere) -> dict[str, Any]:
    """Start a timed review (a reviewer of the finding's tenant). The decision measures
    time from here (server clock)."""
    finding = _finding(session, finding_id, who)
    reviewer = reviewer_in(who, finding.tenant)
    review = ReviewSession(
        finding_id=finding_id,
        reviewer=reviewer.id,
        opened_at=datetime.now(UTC),
        closed=False,
        tenant=finding.tenant,
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


def get_provenance() -> provenance.ProvenanceSource:
    """The engine's provenance, or none when no engine is configured (overridden in tests)."""
    url = get_settings().assessment_engine_url
    return provenance.HttpProvenance(url) if url else provenance.NoProvenance()


Provenance = Annotated[provenance.ProvenanceSource, Depends(get_provenance)]


def check_conflict(source: provenance.ProvenanceSource, finding: Finding, person: str) -> None:
    """409 ``conflict-of-interest`` when the reviewer supplied the system's evidence or
    facts; 503 ``provenance-unavailable`` when the engine cannot say (fail closed)."""
    try:
        record = source.of(finding.system_id)
    except provenance.ProvenanceUnavailableError as exc:
        raise HTTPException(503, {
            "code": "provenance-unavailable",
            "message": f"cannot check for a conflict of interest ({exc}); try again later",
        }) from exc  # fmt: skip
    reasons = provenance.conflicts(record, person)
    if reasons:
        raise HTTPException(409, {
            "code": "conflict-of-interest", "reasons": reasons,
            "message": f"{person} supplied this system's evidence or facts "
                       f"({', '.join(reasons)}) and cannot decide its findings",
        })  # fmt: skip


@app.post("/findings/{finding_id}/decisions", tags=["decisions"])
def post_decision(
    finding_id: str,
    request: DecisionRequest,
    session: Tx,
    who: ReviewerAnywhere,
    sink: Sink,
    source: Provenance,
) -> dict[str, Any]:
    """Record a human decision: accept, accept-with-remediation, reject,
    request-more-evidence or override-verdict (a reviewer of the finding's tenant who did
    not supply the system's evidence or facts: conflict of interest). Performs the side
    effects (POA&M item, ServiceNow tasks through connector-hub) and appends one
    hash-chained log record."""
    finding = _finding(session, finding_id, who)
    reviewer = reviewer_in(who, finding.tenant)
    check_conflict(source, finding, reviewer.id)
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


def _visible_systems(session: Session, who: Principal) -> set[str] | None:
    """Systems of the caller's tenants (from their findings); None: every system."""
    visible = visible_tenants(who)
    if visible is None:
        return None
    rows = session.scalars(select(Finding.system_id).where(Finding.tenant.in_(sorted(visible))))
    return set(rows)


@app.get("/poam", tags=["poam"])
def list_poams(session: ReadSession, user: TenantReader) -> list[dict[str, Any]]:
    rows = session.scalars(select(PoamVersion).order_by(PoamVersion.system_id, PoamVersion.version))
    mine = _visible_systems(session, user)
    latest: dict[str, PoamVersion] = {
        r.system_id: r for r in rows if mine is None or r.system_id in mine
    }
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
    system_id: str, session: ReadSession, user: TenantReader, version: int | None = None
) -> dict[str, Any]:
    """The system's OSCAL 1.1.3 POA&M (latest version unless ``version`` is given)."""
    mine = _visible_systems(session, user)
    if mine is not None and system_id not in mine:
        raise HTTPException(404, f"no POA&M for {system_id}")
    query = select(PoamVersion).where(PoamVersion.system_id == system_id)
    if version is not None:
        query = query.where(PoamVersion.version == version)
    row = session.scalars(query.order_by(PoamVersion.version.desc()).limit(1)).first()
    if row is None:
        raise HTTPException(404, f"no POA&M for {system_id}")
    return row.document


@app.get("/findings/{finding_id}/decisions", tags=["decisions"])
def get_decisions(
    finding_id: str, session: ReadSession, user: TenantReader
) -> list[dict[str, Any]]:
    _finding(session, finding_id, user)
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
    user: LogReader,
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
    # The one chain spans every tenant: verified whole, returning counts and hashes only.
    with tenancy.widened(session, tenancy.ALL_TENANTS):
        result = decision_log.verify_db(
            session, expect_seq=expect_seq, expect_head=expect_head, checkpoints=found
        ).as_dict()
    return {**result, "trusted_sources": sources}


@app.get("/decision-log/checkpoint-status", tags=["decision log"])
def checkpoint_status(session: ReadSession, user: LogReader, sink: Sink) -> dict[str, Any]:
    """Latest external checkpoint from each source, compared with the database head."""
    with tenancy.widened(session, tenancy.ALL_TENANTS):  # seq and hash only
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
def export_log(session: ReadSession, user: LogExporter) -> str:
    """JSON Lines with the exact hashed text of the records of the caller's tenants
    (verify offline with ``review-desk verify-log --file``). TODO(review-desk): with one
    chain for every tenant, an export limited to some tenants does not verify on its own;
    per-tenant chains (Milestone 7, commit 10) fix that. ``GET /decision-log/verify``
    checks the whole chain server-side without showing its content."""
    visible = visible_tenants(user)
    lines = list(decision_log.export_lines(session))
    if visible is not None:
        lines = [line for line in lines if _record_tenant(line) in visible]
    return "\n".join(lines) + "\n"


def _record_tenant(line: str) -> str | None:
    record = json.loads(json.loads(line)["record"])
    tenant = record.get("tenant")
    return str(tenant) if tenant is not None else None


@app.post("/decision-log/verify-export", tags=["decision log"])
async def verify_export(
    request: Request,
    user: LogExporter,
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
def get_checkpoint(session: ReadSession, user: LogReader) -> dict[str, Any]:
    """Current head (seq, hash). Keep it outside the hub to detect truncation later."""
    with tenancy.widened(session, tenancy.ALL_TENANTS):  # seq and hash only
        return decision_log.checkpoint(session)


def _rate_config() -> forecast.RateConfig:
    from pathlib import Path

    return forecast.load_rate_config(Path(get_settings().review_rate_path))


@app.post("/forecast", tags=["forecast"])
def forecast_report(
    session: ReadSession,
    user: ForecastReader,
    report: Annotated[dict[str, Any], Body(description="A rulebook impact report")],
) -> dict[str, Any]:
    """Reviewer hours an impact report will need, per tenant, against weekly capacity
    (the caller's tenants; a governance officer sees every tenant's totals, no findings)."""
    tenants = None if user.has(GOVERNANCE_OFFICER) else visible_tenants(user)
    with tenancy.widened(session, tenants):  # a governance officer: totals, no findings
        return forecast.from_report(session, _rate_config(), report, tenants)


@app.get("/forecast", tags=["forecast"])
def forecast_queue(session: ReadSession, user: ForecastReader) -> dict[str, Any]:
    """Reviewer hours for the open review queue (the caller's tenants)."""
    tenants = None if user.has(GOVERNANCE_OFFICER) else visible_tenants(user)
    with tenancy.widened(session, tenants):  # a governance officer: totals, no findings
        return forecast.from_queue(session, _rate_config(), tenants)
