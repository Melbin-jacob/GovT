"""Endpoints for stored profiles and the AI-system inventory."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Request
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


@router.put(
    "/inventory",
    tags=["inventory"],
    status_code=201,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {"schema": {"type": "object"}},
                "text/csv": {"schema": {"type": "string"}},
            },
            "required": True,
        }
    },
)
async def put_inventory(
    request: Request,
    session: Tx,
    user: User,
    source: Annotated[str, Query(description="Label for the snapshot (CSV uploads)")] = "csv",
) -> dict[str, Any]:
    """Replace the current inventory with a new snapshot. Send JSON
    (``{"source": ..., "systems": [...]}``) or the inventory CSV itself with
    ``Content-Type: text/csv``. Every profile a system names must already be stored."""
    body = await request.body()
    if request.headers.get("content-type", "").startswith("text/csv"):
        try:
            inventory = inv.parse_inventory_csv(body.decode("utf-8-sig"), source=source)
        except (inv.InventoryError, UnicodeDecodeError) as exc:
            errors = exc.errors if isinstance(exc, inv.InventoryError) else [str(exc)]
            raise InvalidCatalogError("inventory CSV is invalid", errors) from exc
    else:
        try:
            inventory = inv.Inventory.model_validate_json(body)
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
