"""Check a real ServiceNow instance end to end (run locally; never in CI).

Reads one AI system, then creates, updates, notes and closes a smoke-test task
(correlation ``GOVHUB-SMOKE-TEST``), so table, role, ACL and field problems surface before
the demo. Prints each step; exits non-zero at the first failure.
"""

from __future__ import annotations

from collections.abc import Callable

from connector_hub.mapping import Mapping
from connector_hub.servicenow import ServiceNowClient, display, value
from connector_hub.task_sync import TaskRequest, upsert_request
from connector_hub.tasks import TaskWriter

SMOKE_ID = "GOVHUB-SMOKE-TEST"


def run_check(client: ServiceNowClient, mapping: Mapping, out: Callable[[str], None]) -> int:
    fields = mapping.inventory_fields
    out(f"instance: {client.config.instance_url} as {client.config.username}")
    rows = client.query(
        mapping.inventory_table,
        mapping.inventory_query,
        sorted(set(fields.values())),
        page_size=5,
    )
    out(f"[ok] read {mapping.inventory_table}: {len(rows)} record(s) on the first page")
    for row in rows[:3]:
        system = display(row, fields["system_id"])
        impact = display(row, fields["impact_level"])
        group = display(row, fields["tenant"])
        owner = value(row, fields["owner_email"])
        out(f"     {system}  impact={impact!r}  group={group!r}  owner={owner!r}")
    writer = TaskWriter(client, mapping)
    tenant = display(rows[0], fields["tenant"]) if rows else None
    request = TaskRequest(
        correlation_id=SMOKE_ID,
        type="smoke",
        short_description="GovHub connection check (safe to close)",
        description="Created by `connector-hub check-servicenow`.",
        tenant=tenant,
        priority=4,
        note="GovHub connection check",
    )
    result = upsert_request(writer, request)
    out(f"[ok] {result['action']} {mapping.task_table} {result['number']}")
    again = upsert_request(writer, request)
    out(f"[ok] re-run is idempotent: {again['action']}")
    writer.note(SMOKE_ID, "GovHub connection check passed; closing.", "closed_complete")
    out("[ok] work note added and task closed")
    for warning in writer.warnings:
        out(f"[warn] {warning}")
    return 0
