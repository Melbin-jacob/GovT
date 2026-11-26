"""FastAPI application for the rulebook service."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from rulebook.db import get_session

# TODO(control-centre): replace with OIDC auth (Entra ID compatible) and role checks.
# Milestone 1 has no authentication beyond this placeholder note.

app = FastAPI(
    title="Canadian AI Governance Hub - Rulebook",
    version="0.1.0",
    description="Versioned OSCAL 1.1.3 catalogs and profiles, rule-change diffs, impact map.",
)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
def ready(session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
    """Readiness: the database is reachable."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ready"}
