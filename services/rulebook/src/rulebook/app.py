"""FastAPI application for the rulebook service."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from govhub_shared.oscal import OscalValidationError, ProfileResolutionError, resolve_profile
from rulebook import store
from rulebook.api_sources import router as sources_router
from rulebook.db import get_session
from rulebook.deps import LangParam, Tx, User
from rulebook.diff import CatalogDiff
from rulebook.profiles import store_loader

app = FastAPI(
    title="Canadian AI Governance Hub - Rulebook",
    version="0.1.0",
    description="Versioned OSCAL 1.1.3 catalogs and profiles, rule-change diffs.",
)


app.include_router(sources_router)


@app.exception_handler(store.StoreError)
def _store_error(_request: Request, exc: store.StoreError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status, content={"detail": exc.message, "errors": exc.errors}
    )


class StoredVersionOut(BaseModel):
    name: str
    version: str
    lang: Literal["en", "fr"]
    uuid: str
    content_hash: str
    controls: int
    withdrawn: int
    created: bool
    warnings: list[str]


class RetireOut(BaseModel):
    catalog: str
    from_version: str
    version: str
    control_id: str
    langs: list[str]
    warnings: list[str]


# --- ops -------------------------------------------------------------------------------


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


# --- catalogs --------------------------------------------------------------------------


@app.post("/catalogs", tags=["catalogs"], status_code=201, response_model=StoredVersionOut)
def import_catalog(
    session: Tx,
    user: User,
    document: Annotated[dict[str, Any], Body(description="OSCAL 1.1.3 catalog document")],
    name: Annotated[str | None, Query(description="Defaults to metadata catalog-name")] = None,
    lang: Annotated[
        Literal["en", "fr"] | None, Query(description="Defaults to metadata language")
    ] = None,
) -> Any:
    """Import a catalog version. Versions are immutable once stored.

    Re-posting identical content returns 200 with ``created: false``; different content
    under an existing version is rejected with 409.
    """
    stored = store.store_catalog(session, document, name=name, lang=lang, created_by=user)
    return JSONResponse(status_code=201 if stored.created else 200, content=asdict(stored))


@app.get("/catalogs", tags=["catalogs"])
def list_catalogs(session: Annotated[Session, Depends(get_session)]) -> list[dict[str, Any]]:
    return store.list_catalogs(session)


@app.get("/catalogs/{name}/versions/{version}", tags=["catalogs"])
def get_catalog_version(
    name: str,
    version: str,
    session: Annotated[Session, Depends(get_session)],
    lang: LangParam = "en",
) -> dict[str, Any]:
    """The stored OSCAL catalog document."""
    return store.get_version(session, name, version, lang).document


@app.post(
    "/catalogs/{name}/versions/{version}/retire-control/{control_id}",
    tags=["catalogs"],
    status_code=201,
    response_model=RetireOut,
)
def retire_control(name: str, version: str, control_id: str, session: Tx, user: User) -> Any:
    """Retire a control: creates the next minor version (every language present at
    ``version``) in which the control remains, with prop ``status = withdrawn``."""
    return store.retire_control(session, name, version, control_id, created_by=user)


def _diff(
    name: str,
    session: Session,
    from_version: str,
    to_version: str,
    lang: str,
) -> CatalogDiff:
    return store.diff_versions(session, name, from_version, to_version, lang)


FromQ = Annotated[str, Query(alias="from", description="Base version")]
ToQ = Annotated[str, Query(alias="to", description="Target version")]


@app.post("/catalogs/{name}/diff", tags=["diff"], response_model=CatalogDiff)
def diff_post(
    name: str,
    session: Annotated[Session, Depends(get_session)],
    from_version: FromQ,
    to_version: ToQ,
    lang: LangParam = "en",
) -> CatalogDiff:
    """Added, retired and changed controls with field-level changes. A change in
    obligation words (must/shall/should/may/required; doit/doivent/peut/peuvent/est tenu)
    is flagged ``obligation-change``."""
    return _diff(name, session, from_version, to_version, lang)


@app.get("/catalogs/{name}/diff", tags=["diff"], response_model=CatalogDiff)
def diff_get(
    name: str,
    session: Annotated[Session, Depends(get_session)],
    from_version: FromQ,
    to_version: ToQ,
    lang: LangParam = "en",
) -> CatalogDiff:
    """Read-only alias of ``POST /catalogs/{name}/diff``."""
    return _diff(name, session, from_version, to_version, lang)


# --- profiles --------------------------------------------------------------------------


class ResolvedProfileOut(BaseModel):
    control_ids: list[str]
    warnings: list[str]
    catalog: dict[str, Any]


@app.post("/profiles/resolve", tags=["profiles"], response_model=ResolvedProfileOut)
def resolve_profile_endpoint(
    session: Annotated[Session, Depends(get_session)],
    profile: Annotated[dict[str, Any], Body(description="OSCAL 1.1.3 profile document")],
) -> Any:
    """Resolve a profile into a flat catalog. Import hrefs must name stored catalog
    versions: ``/catalogs/{name}/versions/{version}?lang=en``."""
    try:
        result = resolve_profile(profile, store_loader(session))
    except OscalValidationError as exc:
        raise store.InvalidCatalogError("profile does not validate", exc.errors) from exc
    except ProfileResolutionError as exc:
        raise store.InvalidCatalogError("profile could not be resolved", exc.errors) from exc
    return {
        "control_ids": result.control_ids,
        "warnings": result.warnings,
        "catalog": result.catalog,
    }


# --- controls --------------------------------------------------------------------------


@app.get("/controls/{control_id}", tags=["controls"])
def get_control(
    control_id: str,
    session: Annotated[Session, Depends(get_session)],
    version: Annotated[str | None, Query(description="Defaults to the latest")] = None,
    catalog: Annotated[str | None, Query(description="Needed if the ID is ambiguous")] = None,
    lang: LangParam = "en",
) -> dict[str, Any]:
    return store.get_control(session, control_id, version=version, catalog_name=catalog, lang=lang)
