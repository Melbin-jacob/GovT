"""Tenants: seeding from a file, listing, and the internal endpoint services read.

Services call ``GET /internal/tenants`` with their own service token, e.g. to check at
startup that every tenant is synthetic before running in demo mode.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from control_centre.db import get_session
from control_centre.models import RESIDENCY_LABELS, Tenant
from govhub_shared.auth import Principal
from govhub_shared.auth.web import require

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]
HUB_SERVICES = ("rulebook", "review-desk", "assessment-engine", "connector-hub")


class TenantFileError(ValueError):
    pass


def tenant_view(t: Tenant) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": {"en": t.name_en, "fr": t.name_fr},
        "synthetic": t.synthetic,
        "residency": t.residency,
    }


def all_tenants(session: Session) -> list[Tenant]:
    return list(session.scalars(select(Tenant).order_by(Tenant.id)))


def seed(session: Session, path: Path, created_by: str = "seed") -> list[str]:
    """Create the file's tenants that do not exist yet (existing ones are left alone)."""
    data = tomllib.loads(path.read_text("utf-8"))
    added = []
    for entry in data.get("tenants", []):
        missing = [
            k for k in ("id", "name_en", "name_fr", "synthetic", "residency") if k not in entry
        ]
        if missing:
            raise TenantFileError(f"{entry.get('id', '?')}: missing {missing}")
        if entry["residency"] not in RESIDENCY_LABELS:
            raise TenantFileError(f"{entry['id']}: residency must be one of {RESIDENCY_LABELS}")
        if session.get(Tenant, entry["id"]) is None:
            session.add(Tenant(
                id=entry["id"], name_en=entry["name_en"], name_fr=entry["name_fr"],
                synthetic=bool(entry["synthetic"]), residency=entry["residency"],
                created_by=created_by,
            ))  # fmt: skip
            added.append(entry["id"])
    session.commit()
    return added


@router.get("/internal/tenants")
def internal_tenants(
    session: SessionDep,
    who: Annotated[Principal, Depends(require(services=HUB_SERVICES))],
) -> list[dict[str, Any]]:
    """Every tenant (IDs, names, synthetic flag, residency label) for hub services."""
    return [tenant_view(t) for t in all_tenants(session)]
