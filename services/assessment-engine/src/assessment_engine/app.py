"""FastAPI application for the assessment engine.

Internal only: reached by control-centre and the demo scripts on localhost or the internal
network. It calls the rulebook and review-desk (internal) and the self-hosted model server
through the model gateway (allow-listed host); nothing else.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from assessment_engine import evidence, rules
from assessment_engine.config import get_settings
from assessment_engine.db import get_session
from assessment_engine.models import EvidenceDocument, SystemFact

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


# --- facts and rule-based checks -------------------------------------------------------


def facts_of(session: Session, system_id: str) -> dict[str, rules.Fact]:
    rows = session.scalars(select(SystemFact).where(SystemFact.system_id == system_id))
    return {r.name: rules.Fact(r.value, r.source) for r in rows}


@app.put("/systems/{system_id}/facts", tags=["facts"])
def put_facts(
    system_id: str,
    session: ReadSession,
    facts: Annotated[
        dict[str, dict[str, Any]],
        Body(embed=True, description='{"name": {"value": ..., "source": "..."}}'),
    ],
    user: Annotated[str, Header(alias="X-GovHub-User")] = "unknown",
) -> dict[str, Any]:
    """Record structured facts about a system (latest value wins; null clears a fact)."""
    now = datetime.now(UTC)
    for name, entry in facts.items():
        if not isinstance(entry, dict) or "value" not in entry:
            raise HTTPException(422, f"fact {name}: expected {{'value': ..., 'source': ...}}")
        row = session.get(SystemFact, (system_id, name))
        if row is None:
            row = SystemFact(system_id=system_id, name=name)
            session.add(row)
        row.value = entry["value"]
        row.source = str(entry.get("source", ""))[:255]
        row.recorded_by = user[:128]
        row.recorded_at = now
    session.commit()
    return {"system_id": system_id, "facts": get_facts(system_id, session)}


@app.get("/systems/{system_id}/facts", tags=["facts"])
def get_facts(system_id: str, session: ReadSession) -> dict[str, Any]:
    return {
        name: {"value": fact.value, "source": fact.source}
        for name, fact in sorted(facts_of(session, system_id).items())
    }


@app.get("/systems/{system_id}/rule-checks", tags=["facts"])
def rule_checks(
    system_id: str,
    session: ReadSession,
    catalog: str,
    as_of: date,
    control: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    """Evaluate the catalog's rule-based checks for the system (no model, no storage)."""
    ruleset = rules.load_rules(Path(get_settings().rules_dir), catalog)
    if ruleset is None:
        raise HTTPException(404, f"no rules file for catalog {catalog}")
    facts = facts_of(session, system_id)
    ids = control or sorted(ruleset.rules)
    return {
        "catalog": catalog,
        "rules_file": ruleset.path,
        "rules_status": ruleset.status,
        "as_of": as_of.isoformat(),
        "results": [rules.assess_rule(ruleset, cid, facts, as_of).as_dict() for cid in ids],
    }
