"""Read the AI-system inventory from ServiceNow and push it to the rulebook.

Missing fields never block the import (proposal: "missing fields never block an
assessment"). A record without a system ID or a name cannot be identified and is
rejected (reported). Any other missing field is recorded as a data gap on the system,
given a safe default, and turned into a data-gap task for the owner's group in
ServiceNow. Data-gap tasks close themselves when the gaps are filled.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from connector_hub.mapping import Mapping
from connector_hub.servicenow import ServiceNowClient, display, value
from connector_hub.tasks import TaskWriter
from govhub_shared.auth.client import ServiceAuth, signing_key

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}
_TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]*$")
UNASSIGNED_TENANT = "unassigned"
# Field labels used in data-gap reports (hub field -> what the owner should fill in).
GAP_LABELS = {
    "tenant": "responsible group (tenant)",
    "department": "department",
    "owner": "owner",
    "owner_email": "owner e-mail",
    "impact_level": "AIA impact level",
    "lifecycle": "lifecycle status",
    "profiles": "GovHub profiles",
}


def parse_impact_level(raw: str) -> int | None:
    text = raw.strip().upper().removeprefix("LEVEL").strip()
    if text in _ROMAN:
        return _ROMAN[text]
    if text.isdigit() and 1 <= int(text) <= 4:
        return int(text)
    return None


@dataclass
class PullResult:
    systems: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)

    @property
    def gaps(self) -> dict[str, list[str]]:
        return {s["system_id"]: s["data_gaps"] for s in self.systems if s["data_gaps"]}


def pull_inventory(client: ServiceNowClient, mapping: Mapping) -> PullResult:
    fields = mapping.inventory_fields
    rows = client.query(
        mapping.inventory_table, mapping.inventory_query, sorted(set(fields.values()))
    )
    result = PullResult()
    for row in rows:

        def get(name: str, *, shown: bool = True, row: dict[str, Any] = row) -> str:
            column = fields[name]
            return (display(row, column) if shown else value(row, column)).strip()

        system_id, name = get("system_id"), get("name")
        if not system_id or not name or not _TOKEN.match(system_id):
            result.rejected.append(
                f"record {value(row, 'sys_id') or '?'}: missing or invalid system ID/name"
            )
            continue
        gaps: list[str] = []
        tenant = get("tenant")
        if not tenant or not _TOKEN.match(tenant):
            gaps.append("tenant")
            tenant = UNASSIGNED_TENANT
        department = get("department") or "(unknown)"
        if department == "(unknown)":
            gaps.append("department")
        owner = get("owner") or "(unknown)"
        if owner == "(unknown)":
            gaps.append("owner")
        owner_email = get("owner_email", shown=False) or None
        if owner_email is None or "@" not in owner_email:
            gaps.append("owner_email")
            owner_email = None
        impact = parse_impact_level(get("impact_level", shown=False)) or parse_impact_level(
            get("impact_level")
        )
        if impact is None:
            gaps.append("impact_level")
        lifecycle = mapping.lifecycle.get(get("lifecycle"), "unknown")
        if lifecycle == "unknown":
            gaps.append("lifecycle")
        profiles = [p.strip() for p in get("profiles").split(";") if p.strip()]
        if not profiles:
            gaps.append("profiles")
        result.systems.append(
            {
                "system_id": system_id,
                "name": name,
                "tenant": tenant,
                "department": department,
                "owner": owner,
                "owner_email": owner_email,
                "impact_level": impact,
                "lifecycle": lifecycle,
                "profiles": profiles,
                "notes": get("notes") or None,
                "data_gaps": gaps,
            }
        )
    return result


def sync_data_gap_tasks(writer: TaskWriter, result: PullResult) -> list[dict[str, Any]]:
    """One data-gap task per system with gaps; close it when the gaps are gone."""
    outcomes: list[dict[str, Any]] = []
    for system in result.systems:
        correlation = f"GAP-{system['system_id']}"
        gaps = system["data_gaps"]
        if not gaps:
            existing = writer.find(correlation)
            closed = {
                writer.mapping.task_states[k]
                for k in writer.mapping.task_states
                if k.startswith("closed")
            }
            state_field = writer.mapping.task_fields["state"]
            if existing is not None and value(existing, state_field) not in closed:
                writer.note(
                    correlation, "All data gaps resolved; closed by GovHub.", "closed_complete"
                )
                outcomes.append({"system_id": system["system_id"], "action": "closed"})
            continue
        missing = ", ".join(GAP_LABELS[g] for g in gaps)
        fingerprint = hashlib.sha256(missing.encode()).hexdigest()[:8]
        action, record = writer.upsert(
            correlation,
            {
                "short_description": f"Complete the inventory record of {system['name']}",
                "description": (
                    f"GovHub could not read these fields for {system['system_id']} "
                    f"({system['name']}): {missing}. Until they are filled in, the system is "
                    "ranked as unknown impact (treated as level IV) and checks that depend on "
                    "them are 'unable to determine'. Fill them in on the configuration item."
                ),
                "assignment_group": writer.group(
                    None if system["tenant"] == "unassigned" else system["tenant"]
                ),
                "assigned_to": writer.user(system["owner_email"]),
                "cmdb_ci": writer.ci(system["system_id"]),
                "priority": "2",
                "state": writer.mapping.task_states["open"],
                "type": "data-gap",
                "reference": f"{system['system_id']}:{fingerprint}",
            },
            note=f"GovHub inventory sync: missing {missing}",
        )
        outcomes.append(
            {"system_id": system["system_id"], "action": action, "gaps": gaps, **record}
        )
    return outcomes


def push_to_rulebook(
    rulebook_url: str, result: PullResult, source: str, http: httpx.Client | None = None
) -> dict[str, Any]:
    """Store the pulled inventory as a new rulebook snapshot (internal service call, signed
    as connector-hub's sync job: all tenants, since a snapshot replaces every tenant's)."""
    client = http or httpx.Client(
        base_url=rulebook_url, timeout=30.0,
        auth=ServiceAuth(signing_key("connector-hub"), "rulebook", all_tenants=True),
    )  # fmt: skip
    response = client.put("/inventory", json={"source": source, "systems": result.systems})
    if response.status_code >= 400:
        raise RuntimeError(f"rulebook rejected the inventory: {response.text}")
    data: dict[str, Any] = response.json()
    return data
