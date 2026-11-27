"""FastAPI application for the assessment engine.

Internal only: reached by control-centre and the demo scripts on localhost or the internal
network. It calls the rulebook and review-desk (internal) and the self-hosted model server
through the model gateway (allow-listed host); nothing else.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from assessment_engine import evidence
from assessment_engine.config import get_settings
from assessment_engine.db import get_session
from assessment_engine.models import EvidenceDocument

app = FastAPI(title="Canadian AI Governance Hub - Assessment engine", version="0.1.0")
ReadSession = Annotated[Session, Depends(get_session)]


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
def ready(session: ReadSession) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ready"}


@app.get("/evidence-policy", tags=["evidence"])
def evidence_policy() -> dict[str, Any]:
    """How evidence is protected and kept. Retention is a PLACEHOLDER owned by
    control-centre later (TODO(control-centre)): nothing is deleted automatically yet."""
    settings = get_settings()
    return {
        "service_encryption": "aes-256-gcm" if settings.evidence_key else "off",
        "volume_encryption": "platform (encrypted volume where the platform allows)",
        "retention_days": settings.evidence_retention_days,
        "retention_status": "PLACEHOLDER: owned by control-centre (TODO(control-centre))",
        "passage_text_logged": False,
    }


# --- evidence --------------------------------------------------------------------------


@app.post("/systems/{system_id}/evidence", tags=["evidence"], status_code=201)
async def upload_evidence(
    system_id: str,
    session: ReadSession,
    file: Annotated[UploadFile, File(description="TXT, Markdown, HTML, PDF or DOCX")],
    user: Annotated[str, Header(alias="X-GovHub-User")] = "unknown",
) -> dict[str, Any]:
    """Store and index one evidence file for a system (same file twice: no duplicate)."""
    settings = get_settings()
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"file larger than {settings.max_upload_bytes} bytes")
    doc, rows, created = evidence.ingest(
        session,
        evidence.store_for(settings),
        system_id=system_id,
        filename=file.filename or "upload",
        data=data,
        uploaded_by=user,
    )
    session.commit()
    return {**evidence.document_view(doc, rows), "created": created}


@app.get("/systems/{system_id}/evidence", tags=["evidence"])
def list_evidence(system_id: str, session: ReadSession) -> list[dict[str, Any]]:
    docs = session.scalars(
        select(EvidenceDocument)
        .where(EvidenceDocument.system_id == system_id)
        .order_by(EvidenceDocument.uploaded_at)
    )
    return [evidence.document_view(d, evidence.passages_of(session, d.id)) for d in docs]


@app.get("/evidence/{document_id}/passages", tags=["evidence"])
def document_passages(document_id: str, session: ReadSession) -> list[dict[str, Any]]:
    if session.get(EvidenceDocument, document_id) is None:
        raise HTTPException(404, "evidence document not found")
    return [evidence.passage_view(p) for p in evidence.passages_of(session, document_id)]


@app.get("/systems/{system_id}/evidence/search", tags=["evidence"])
def search_evidence(
    system_id: str,
    session: ReadSession,
    q: Annotated[str, Query(min_length=2)],
    k: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[dict[str, Any]]:
    """Best-matching passages (BM25) for a query, e.g. a control statement."""
    return [
        {**evidence.passage_view(r.passage), "score": round(r.score, 4)}
        for r in evidence.retrieve(session, system_id, q, k)
    ]
