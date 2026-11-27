"""AI-system inventory: CSV parsing, validation, snapshots, and stored profiles.

Stands in for the ServiceNow CMDB until connector-hub exists.
TODO(connector-hub): feed snapshots from the CMDB with configurable field mappings.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from govhub_shared import OSCAL_NS
from govhub_shared.oscal import OscalValidationError, normalize, validate
from rulebook.models import AISystem, InventorySnapshot, StoredProfile
from rulebook.store import InvalidCatalogError, NotFoundError

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}
ROMAN_OF = {v: k for k, v in ROMAN.items()}
_ID_PATTERN = r"^[A-Za-z_][A-Za-z0-9._-]*$"
Lifecycle = Literal["development", "pilot", "production", "retired"]
CSV_COLUMNS = {
    "System ID": "system_id",
    "Name": "name",
    "Tenant": "tenant",
    "Department": "department",
    "Owner": "owner",
    "Owner email": "owner_email",
    "AIA impact level": "impact_level",
    "Lifecycle": "lifecycle",
    "Profiles": "profiles",
    "Notes": "notes",
}


class SystemRecord(BaseModel):
    """The standard AI-system record every connector maps into."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    system_id: str = Field(pattern=_ID_PATTERN)
    name: str = Field(min_length=1)
    tenant: str = Field(pattern=_ID_PATTERN)
    department: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    owner_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    impact_level: int = Field(ge=1, le=4, description="AIA impact level, 1-4 (I-IV)")
    lifecycle: Lifecycle
    profiles: list[str] = []
    notes: str | None = None

    @field_validator("impact_level", mode="before")
    @classmethod
    def _roman(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().upper() in ROMAN:
            return ROMAN[value.strip().upper()]
        return value

    @field_validator("profiles", mode="before")
    @classmethod
    def _split(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [p.strip() for p in value.split(";") if p.strip()]
        return value

    @property
    def impact_label(self) -> str:
        return ROMAN_OF[self.impact_level]


class Inventory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = "api"
    systems: list[SystemRecord]

    def content_hash(self) -> str:
        rows = sorted(
            (s.model_dump(mode="json") for s in self.systems), key=lambda r: r["system_id"]
        )
        canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class InventoryError(ValueError):
    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = list(errors)
        super().__init__("inventory is invalid:\n" + "\n".join(f"  - {e}" for e in errors))


def parse_inventory_csv(text: str, source: str = "csv") -> Inventory:
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in CSV_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise InventoryError([f"missing column(s): {missing}"])
    errors: list[str] = []
    systems: list[SystemRecord] = []
    for line, row in enumerate(reader, start=2):
        data = {field: (row.get(col) or "").strip() for col, field in CSV_COLUMNS.items()}
        data["notes"] = data["notes"] or None
        try:
            systems.append(SystemRecord.model_validate(data))
        except ValidationError as exc:
            for err in exc.errors():
                errors.append(f"line {line}: {'.'.join(map(str, err['loc']))}: {err['msg']}")
    errors += _duplicates(systems)
    if errors:
        raise InventoryError(errors)
    return Inventory(source=source, systems=systems)


def _duplicates(systems: Sequence[SystemRecord]) -> list[str]:
    ids = [s.system_id for s in systems]
    return [f"duplicate System ID {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]


# --- stored profiles -------------------------------------------------------------------


def profile_name(document: Mapping[str, Any]) -> str | None:
    for prop in document["profile"]["metadata"].get("props", []):
        if prop.get("name") == "profile-name" and prop.get("ns") == OSCAL_NS:
            return str(prop["value"])
    return None


def put_profile(
    session: Session, name: str, document: Mapping[str, Any], *, user: str
) -> tuple[bool, str]:
    """Create or replace a named profile. Returns (created, content hash)."""
    if not re.match(_ID_PATTERN, name):
        raise InvalidCatalogError(f"profile name {name!r} is not a valid token")
    try:
        validate(document, "profile")
        doc = normalize(document, "profile")
    except OscalValidationError as exc:
        raise InvalidCatalogError("profile does not validate", exc.errors) from exc
    declared = profile_name(doc)
    if declared is not None and declared != name:
        raise InvalidCatalogError(f"profile-name prop {declared!r} does not match {name!r}")
    digest = hashlib.sha256(
        json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    row = session.get(StoredProfile, name)
    if row is None:
        session.add(StoredProfile(name=name, document=doc, content_hash=digest, updated_by=user))
        return True, digest
    row.document, row.content_hash, row.updated_by = doc, digest, user
    return False, digest


def get_profile(session: Session, name: str) -> dict[str, Any]:
    row = session.get(StoredProfile, name)
    if row is None:
        raise NotFoundError(f"profile {name!r} not found")
    return row.document


def list_profiles(session: Session) -> list[dict[str, Any]]:
    return [
        {
            "name": row.name,
            "title": row.document["profile"]["metadata"]["title"],
            "content_hash": row.content_hash,
        }
        for row in session.scalars(select(StoredProfile).order_by(StoredProfile.name))
    ]


# --- inventory snapshots ---------------------------------------------------------------


def store_inventory(session: Session, inventory: Inventory, *, user: str) -> dict[str, Any]:
    """Replace the current inventory with a new snapshot (old snapshots are kept)."""
    errors = _duplicates(inventory.systems)
    known = {name for (name,) in session.execute(select(StoredProfile.name))}
    for system in inventory.systems:
        unknown = [p for p in system.profiles if p not in known]
        if unknown:
            errors.append(f"{system.system_id}: unknown profile(s) {unknown}")
    if errors:
        raise InvalidCatalogError("inventory is invalid", errors)
    snapshot = InventorySnapshot(
        content_hash=inventory.content_hash(), source=inventory.source, imported_by=user
    )
    session.add(snapshot)
    session.flush()
    for system in inventory.systems:
        session.add(AISystem(snapshot_id=snapshot.id, **system.model_dump()))
    session.flush()
    return {
        "snapshot": snapshot.id,
        "content_hash": snapshot.content_hash,
        "systems": len(inventory.systems),
        "tenants": sorted({s.tenant for s in inventory.systems}),
    }


def current_inventory(session: Session) -> tuple[InventorySnapshot, list[SystemRecord]]:
    snapshot = session.scalar(select(InventorySnapshot).order_by(InventorySnapshot.id.desc()))
    if snapshot is None:
        raise NotFoundError("no inventory has been imported")
    systems = [
        SystemRecord(
            system_id=s.system_id,
            name=s.name,
            tenant=s.tenant,
            department=s.department,
            owner=s.owner,
            owner_email=s.owner_email,
            impact_level=s.impact_level,
            lifecycle=s.lifecycle,
            profiles=list(s.profiles),
            notes=s.notes,
        )
        for s in snapshot.systems
    ]
    return snapshot, systems
