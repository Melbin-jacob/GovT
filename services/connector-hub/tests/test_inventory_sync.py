"""Inventory pull from (mock) ServiceNow, data gaps, data-gap tasks, push to the rulebook."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from mock_support import REPO, mock_client

from connector_hub import app as app_module
from connector_hub.inventory import (
    parse_impact_level,
    pull_inventory,
    push_to_rulebook,
    sync_data_gap_tasks,
)
from connector_hub.mapping import load_mapping
from connector_hub.tasks import TaskWriter

MAPPING = load_mapping(REPO / "data" / "config" / "servicenow-mapping.toml")


@pytest.mark.parametrize(
    ("raw", "level"),
    [("4", 4), ("IV", 4), ("Level II", 2), ("ii", 2), ("", None), ("5", None), ("high", None)],
)
def test_parse_impact_level(raw: str, level: int | None) -> None:
    assert parse_impact_level(raw) == level


def test_pull_maps_fields_and_records_gaps() -> None:
    client, _ = mock_client()
    result = pull_inventory(client, MAPPING)
    by_id = {s["system_id"]: s for s in result.systems}
    assert sorted(by_id) == [f"SYS-00{i}" for i in range(1, 10)]
    sys1 = by_id["SYS-001"]
    assert sys1 == {
        "system_id": "SYS-001",
        "name": "Sample Benefits Triage Assistant (fictional)",
        "tenant": "agency-sample-benefits",
        "department": "Agency of Sample Benefits (fictional)",
        "owner": "Director, Example Benefits Program",
        "owner_email": "benefits.owner@example.invalid",
        "impact_level": 4,
        "lifecycle": "production",
        "profiles": ["dadm-level-ii-plus", "widgets-all"],
        "notes": "FICTIONAL demo record",
        "data_gaps": [],
    }
    assert by_id["SYS-005"]["lifecycle"] == "pilot"
    assert by_id["SYS-008"]["lifecycle"] == "retired"
    assert result.gaps == {"SYS-009": ["owner", "owner_email", "impact_level", "profiles"]}
    gap = by_id["SYS-009"]
    assert (gap["impact_level"], gap["owner_email"], gap["profiles"]) == (None, None, [])
    assert result.rejected == []


def test_matches_the_csv_inventory() -> None:
    """The mock seed was generated from systems.csv: SYS-001..008 must round-trip."""
    from rulebook.inventory import parse_inventory_csv

    csv_systems = {
        s.system_id: s.model_dump(mode="json")
        for s in parse_inventory_csv(
            (REPO / "data/inventory/systems.csv").read_text("utf-8")
        ).systems
    }
    client, _ = mock_client()
    pulled = {s["system_id"]: s for s in pull_inventory(client, MAPPING).systems}
    for system_id, expected in csv_systems.items():
        assert pulled[system_id] == expected


def test_data_gap_tasks_are_idempotent_and_close_when_fixed() -> None:
    client, app = mock_client()
    writer = TaskWriter(client, MAPPING)
    first = sync_data_gap_tasks(writer, pull_inventory(client, MAPPING))
    assert [(o["system_id"], o["action"]) for o in first] == [("SYS-009", "created")]
    second = sync_data_gap_tasks(writer, pull_inventory(client, MAPPING))
    assert [(o["system_id"], o["action"]) for o in second] == [("SYS-009", "unchanged")]
    (task,) = app.state.mock.tables["u_govhub_task"]
    assert task["u_govhub_type"] == "data-gap"
    assert task["correlation_id"] == "GAP-SYS-009"
    assert "AIA impact level" in task["description"]
    assert task["assignment_group"]  # resolved to the tenant group's sys_id
    assert task["cmdb_ci"]

    # The owner fills in the record: the task closes once, and stays closed.
    ci = next(
        r for r in app.state.mock.tables["cmdb_ci_business_app"] if r["correlation_id"] == "SYS-009"
    )
    owner = app.state.mock.tables["sys_user"][0]
    ci.update(
        {"owned_by": owner["sys_id"], "u_aia_impact_level": "2", "u_govhub_profiles": "widgets-all"}
    )
    third = sync_data_gap_tasks(writer, pull_inventory(client, MAPPING))
    assert [(o["system_id"], o["action"]) for o in third] == [("SYS-009", "closed")]
    assert task["state"] == "3"
    assert sync_data_gap_tasks(writer, pull_inventory(client, MAPPING)) == []


def test_unresolvable_lookups_warn_not_fail() -> None:
    client, _ = mock_client()
    writer = TaskWriter(client, MAPPING)
    assert writer.user("nobody@example.invalid") == ""
    assert writer.group(None) == ""
    assert writer.warnings == ["no sys_user record with email=nobody@example.invalid"]


def test_push_payload() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content), path=request.url.path, method=request.method)
        return httpx.Response(201, json={"snapshot": 1, "systems": 9})

    client, _ = mock_client()
    result = pull_inventory(client, MAPPING)
    http = httpx.Client(base_url="http://rulebook", transport=httpx.MockTransport(handler))
    assert push_to_rulebook("http://rulebook", result, "servicenow:mock", http) == {
        "snapshot": 1,
        "systems": 9,
    }
    assert (seen["method"], seen["path"], seen["source"]) == (
        "PUT",
        "/inventory",
        "servicenow:mock",
    )
    assert len(seen["systems"]) == 9


def test_sync_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = mock_client()
    app_module.app.dependency_overrides[app_module.get_client] = lambda: client
    pushed: list[str] = []
    monkeypatch.setattr(
        app_module.inventory,
        "push_to_rulebook",
        lambda url, result, source: pushed.append(source) or {"snapshot": 7},
    )
    try:
        api = TestClient(app_module.app)
        dry = api.post("/inventory/sync", params={"dry_run": True}).json()
        assert dry["systems"] == 9 and pushed == []
        body = api.post("/inventory/sync").json()
        assert body["rulebook"] == {"snapshot": 7}
        assert body["data_gaps"] == {
            "SYS-009": ["owner", "owner_email", "impact_level", "profiles"]
        }
        assert body["data_gap_tasks"][0]["action"] == "created"
    finally:
        app_module.app.dependency_overrides.clear()


def test_sync_endpoint_without_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for key in ("SERVICENOW_INSTANCE_URL", "SERVICENOW_USERNAME", "SERVICENOW_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SERVICENOW_ENV_FILE", str(tmp_path / "absent"))
    resp = TestClient(app_module.app).post("/inventory/sync")
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]
