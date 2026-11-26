"""Endpoints for source documents (official policy text)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from rulebook.db import get_session
from rulebook.deps import LangParam, Tx, User
from rulebook.sources import store as source_store
from rulebook.store import NotFoundError

router = APIRouter(prefix="/sources", tags=["sources"])
ReadSession = Annotated[Session, Depends(get_session)]


@router.post("", status_code=201)
def import_source(
    session: Tx,
    user: User,
    document: Annotated[dict[str, Any], Body(description="Full source document (with text)")],
) -> JSONResponse:
    """Store a source document version. Immutable: identical content returns 200 with
    ``created: false``, different content under an existing version returns 409."""
    doc, created, parity = source_store.store_source(session, document, created_by=user)
    return JSONResponse(
        status_code=201 if created else 200,
        content={
            "instrument": doc.instrument,
            "version": doc.version,
            "lang": doc.lang,
            "synthetic": doc.synthetic,
            "clauses": len(doc.clauses),
            "created": created,
            "parse_warnings": list(doc.warnings),
            "parity_warnings": parity,
        },
    )


@router.get("")
def list_sources(session: ReadSession) -> list[dict[str, Any]]:
    return source_store.list_sources(session)


@router.get("/{instrument}/versions/{version}")
def get_source(
    instrument: str, version: str, session: ReadSession, lang: LangParam = "en"
) -> dict[str, Any]:
    doc = source_store.get_source(session, instrument, version, lang)
    return doc.model_dump(mode="json", exclude_none=True)


@router.get("/{instrument}/versions/{version}/clauses/{number}")
def get_clause(
    instrument: str, version: str, number: str, session: ReadSession, lang: LangParam = "en"
) -> dict[str, Any]:
    doc = source_store.get_source(session, instrument, version, lang)
    clause = doc.clause(number)
    if clause is None:
        raise NotFoundError(f"clause {number} not in {instrument} {version} ({lang})")
    return {
        "instrument": instrument,
        "version": version,
        "lang": lang,
        **clause.model_dump(mode="json", exclude_none=True),
    }
