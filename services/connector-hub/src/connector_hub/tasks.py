"""Create and update hub tasks in ServiceNow (custom table extending task, never incident).

Tasks are matched by ``correlation_id`` (the hub's own task ID), so running the same sync
twice updates instead of duplicating. Reference fields are resolved by lookup: tenant ->
group name, owner e-mail -> user, system ID -> configuration item. A failed lookup leaves
the field empty and is reported as a warning, never an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from connector_hub.mapping import Mapping
from connector_hub.servicenow import ServiceNowClient, value

Action = Literal["created", "updated", "unchanged"]


@dataclass
class TaskWriter:
    client: ServiceNowClient
    mapping: Mapping
    warnings: list[str] = field(default_factory=list)
    _cache: dict[tuple[str, str], str | None] = field(default_factory=dict)

    def _lookup(self, kind: str, key: str | None) -> str:
        if not key:
            return ""
        cache_key = (kind, key)
        if cache_key not in self._cache:
            table = self.mapping.lookups[f"{kind}_table"]
            column = self.mapping.lookups[f"{kind}_field"]
            row = self.client.find_one(table, f"{column}={key}", ["sys_id"])
            self._cache[cache_key] = value(row, "sys_id") if row else None
            if row is None:
                self.warnings.append(f"no {table} record with {column}={key}")
        return self._cache[cache_key] or ""

    def group(self, tenant: str | None) -> str:
        return self._lookup("group", tenant)

    def user(self, email: str | None) -> str:
        return self._lookup("user", email)

    def ci(self, system_id: str | None) -> str:
        return self._lookup("ci", system_id)

    def find(self, correlation_id: str) -> dict[str, Any] | None:
        column = self.mapping.task_fields["correlation_id"]
        fields = ["sys_id", "number", *self.mapping.task_fields.values()]
        return self.client.find_one(
            self.mapping.task_table, f"{column}={correlation_id}", sorted(set(fields))
        )

    def upsert(
        self,
        correlation_id: str,
        values: dict[str, Any],
        *,
        note: str | None = None,
        create_only: frozenset[str] = frozenset({"state"}),
    ) -> tuple[Action, dict[str, Any]]:
        """Create the task, or update only the fields that differ. ``values`` uses hub field
        names (see the mapping); references are already resolved to sys_ids. Fields in
        ``create_only`` (by default the state) are set on creation only, so a re-sync never
        reopens a task someone is already working on."""
        values = {
            **values,
            "correlation_id": correlation_id,
            "correlation_display": self.mapping.correlation_display,
        }
        existing = self.find(correlation_id)
        if existing is None:
            if note:
                values["work_notes"] = note
            created = self.client.create(self.mapping.task_table, self.mapping.task_values(values))
            return "created", {"sys_id": created["sys_id"], "number": created.get("number", "")}
        changed = {
            k: v
            for k, v in values.items()
            if k not in create_only
            and str(v if v is not None else "") != value(existing, self.mapping.task_fields[k])
        }
        if not changed:
            return "unchanged", {
                "sys_id": value(existing, "sys_id"),
                "number": value(existing, "number"),
            }
        if note:
            changed["work_notes"] = note
        self.client.update(
            self.mapping.task_table, value(existing, "sys_id"), self.mapping.task_values(changed)
        )
        return "updated", {"sys_id": value(existing, "sys_id"), "number": value(existing, "number")}

    def note(self, correlation_id: str, text: str, state: str | None = None) -> dict[str, Any]:
        """Append a work note (and optionally set the state by name, e.g. closed_complete)."""
        existing = self.find(correlation_id)
        if existing is None:
            raise LookupError(f"no task with correlation_id {correlation_id}")
        values: dict[str, Any] = {"work_notes": text}
        if state:
            values["state"] = self.mapping.task_states[state]
        self.client.update(
            self.mapping.task_table, value(existing, "sys_id"), self.mapping.task_values(values)
        )
        return {"sys_id": value(existing, "sys_id"), "number": value(existing, "number")}
