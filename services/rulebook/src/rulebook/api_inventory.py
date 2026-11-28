"""Endpoints for stored profiles and the AI-system inventory."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from govhub_shared.auth import TENANT_ADMIN
from rulebook import inventory as inv
from rulebook.access import (
    AssignProfiles,
    ReadTenantData,
    SyncInventory,
    govern_content,
    read_shared,
    require_assignment,
    require_sync_scope,
    visible_tenants,
)
from rulebook.db import get_session
from rulebook.deps import Tx, User
from rulebook.store import InvalidCatalogError, NotFoundError

router = APIRouter()
ReadSession = Annotated[Session, Depends(get_session)]


@router.put("/profiles/{name}", tags=["profiles"], dependencies=[Depends(govern_content)])
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


@router.get("/profiles", tags=["profiles"], dependencies=[Depends(read_shared)])
def list_profiles(session: ReadSession) -> list[dict[str, Any]]:
    return inv.list_profiles(session)


@router.get("/profiles/{name}", tags=["profiles"], dependencies=[Depends(read_shared)])
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
    who: SyncInventory,
    source: Annotated[str, Query(description="Label for the snapshot (CSV uploads)")] = "csv",
) -> dict[str, Any]:
    """Replace the current inventory with a new snapshot. Send JSON
    (``{"source": ..., "systems": [...]}``) or the inventory CSV itself with
    ``Content-Type: text/csv``. Every profile a system names must already be stored.
    connector-hub's sync job only (all tenants: a snapshot replaces every tenant's systems)."""
    require_sync_scope(who)
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
    who: ReadTenantData,
    tenant: Annotated[str | None, Query(description="Only this tenant")] = None,
) -> dict[str, Any]:
    """The current snapshot's systems of the caller's tenants."""
    visible = visible_tenants(who)
    snapshot, systems = inv.current_inventory(session)
    systems = [s for s in systems if visible is None or s.tenant in visible]
    return {
        "snapshot": snapshot.id,
        "content_hash": snapshot.content_hash,
        "source": snapshot.source,
        "systems": [
            s.model_dump(mode="json") for s in systems if tenant is None or s.tenant == tenant
        ],
    }


@router.get("/systems/{system_id}", tags=["inventory"])
def get_system(system_id: str, session: ReadSession, who: ReadTenantData) -> dict[str, Any]:
    return _system(session, system_id, visible_tenants(who)).model_dump(mode="json")


def _system(session: Session, system_id: str, visible: frozenset[str] | None) -> inv.SystemRecord:
    """A system of the caller's tenants (another tenant's system is "not found")."""
    _, systems = inv.current_inventory(session)
    for system in systems:
        if system.system_id == system_id and (visible is None or system.tenant in visible):
            return system
    raise NotFoundError(f"system {system_id} not in the current inventory")


class ProfileChoice(BaseModel):
    profiles: list[str]


@router.put("/systems/{system_id}/profiles", tags=["inventory"])
def assign_profiles(
    system_id: str, body: ProfileChoice, session: Tx, who: AssignProfiles
) -> dict[str, Any]:
    """The tenant-admin chooses which stored profiles apply to one of the tenant's
    systems (it replaces the inventory's profiles for that system in impact reports)."""
    system = _system(session, system_id, who.tenants_with(TENANT_ADMIN))
    require_assignment(who, system.tenant)
    try:
        return inv.assign_profiles(session, system, body.profiles, user=who.id)
    except inv.InventoryError as exc:
        raise InvalidCatalogError("profile assignment is invalid", exc.errors) from exc
