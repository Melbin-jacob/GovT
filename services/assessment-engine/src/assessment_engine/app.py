"""FastAPI application for the assessment engine.

Internal only: reached by control-centre and the demo scripts on localhost or the internal
network. It calls the rulebook and review-desk (internal) and the self-hosted model server
through the model gateway (allow-listed host); nothing else.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from assessment_engine.config import get_settings
from assessment_engine.db import get_session

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
