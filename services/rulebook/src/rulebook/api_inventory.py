"""Endpoints for stored profiles and the AI-system inventory."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from rulebook import inventory as inv
from rulebook.db import get_session
from rulebook.deps import Tx, User
from rulebook.store import InvalidCatalogError, NotFoundError

router = APIRouter()
ReadSession = Annotated[Session, Depends(get_session)]


@router.put("/profiles/{name}", tags=["profiles"])
def put_profile(
    name: str,
    session: Tx,
    user: User,
    document: Annotated[dict[str, Any], Body(description="OSCAL 1.1.3 profile document")],
) -> JSONResponse:
    """Create or replace a named profile (profiles are configuration, not versioned rules)."""
    created, digest = inv.put_profile(session, name, document, user=user)
    return JSONResponse(
        status_code=201 if created else 200,
        content={"name": name, "created": created, "content_hash": digest},
    )


@router.get("/profiles", tags=["profiles"])
def list_profiles(session: ReadSession) -> list[dict[str, Any]]:
    return inv.list_profiles(session)


@router.get("/profiles/{name}", tags=["profiles"])
def get_profile(name: str, session: ReadSession) -> dict[str, Any]:
    return inv.get_profile(session, name)


@router.put("/inventory", tags=["inventory"], status_code=201)
def put_inventory(
    session: Tx,
    user: User,
    payload: Annotated[dict[str, Any], Body(description='{"source": ..., "systems": [...]}')],
) -> dict[str, Any]:
    """Replace the current inventory with a new snapshot. Every profile a system names must
    already be stored."""
    try:
        inventory = inv.Inventory.model_validate(payload)
    except ValidationError as exc:
        raise InvalidCatalogError(
            "inventory is invalid",
            [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()],
        ) from exc
    return inv.store_inventory(session, inventory, user=user)


@router.get("/inventory", tags=["inventory"])
def get_inventory(
    session: ReadSession,
    tenant: Annotated[str | None, Query(description="Only this tenant")] = None,
) -> dict[str, Any]:
    snapshot, systems = inv.current_inventory(session)
    return {
        "snapshot": snapshot.id,
        "content_hash": snapshot.content_hash,
        "source": snapshot.source,
        "systems": [
            s.model_dump(mode="json") for s in systems if tenant is None or s.tenant == tenant
        ],
    }


@router.get("/systems/{system_id}", tags=["inventory"])
def get_system(system_id: str, session: ReadSession) -> dict[str, Any]:
    _, systems = inv.current_inventory(session)
    for system in systems:
        if system.system_id == system_id:
            return system.model_dump(mode="json")
    raise NotFoundError(f"system {system_id} not in the current inventory")
