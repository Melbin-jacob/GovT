"""Field mapping between the hub and ServiceNow, loaded from TOML (no code changes)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path("data/config/servicenow-mapping.toml")
INVENTORY_FIELDS = (
    "system_id",
    "name",
    "tenant",
    "department",
    "owner",
    "owner_email",
    "impact_level",
    "lifecycle",
    "profiles",
    "notes",
)
TASK_FIELDS = (
    "correlation_id",
    "correlation_display",
    "short_description",
    "description",
    "assignment_group",
    "assigned_to",
    "priority",
    "due_date",
    "cmdb_ci",
    "state",
    "work_notes",
    "type",
    "reference",
)


@dataclass(frozen=True)
class Mapping:
    inventory_table: str
    inventory_query: str
    inventory_fields: dict[str, str]
    lifecycle: dict[str, str]
    task_table: str
    correlation_display: str
    task_fields: dict[str, str]
    task_states: dict[str, str]
    lookups: dict[str, str]

    def task_values(self, values: dict[str, object]) -> dict[str, object]:
        """Hub task fields -> ServiceNow column names (unknown keys are an error)."""
        unknown = sorted(set(values) - set(self.task_fields))
        if unknown:
            raise ValueError(f"no ServiceNow mapping for task field(s) {unknown}")
        return {self.task_fields[k]: v for k, v in values.items()}


def load_mapping(path: Path = DEFAULT_PATH) -> Mapping:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    inventory, tasks = data["inventory"], data["tasks"]
    missing = [f for f in INVENTORY_FIELDS if f not in inventory["fields"]]
    missing += [f"tasks.{f}" for f in TASK_FIELDS if f not in tasks["fields"]]
    if missing:
        raise ValueError(f"{path}: mapping missing {missing}")
    return Mapping(
        inventory_table=inventory["table"],
        inventory_query=inventory.get("query", ""),
        inventory_fields=dict(inventory["fields"]),
        lifecycle=dict(inventory.get("lifecycle", {})),
        task_table=tasks["table"],
        correlation_display=tasks.get("correlation_display", "GovHub"),
        task_fields=dict(tasks["fields"]),
        task_states=dict(tasks["states"]),
        lookups=dict(data["lookups"]),
    )
