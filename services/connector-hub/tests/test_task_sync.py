"""Impact-report tasks and review-desk requests -> u_govhub_task in (mock) ServiceNow."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mock_support import REPO, mock_client

from connector_hub import app as app_module
from connector_hub.live_check import SMOKE_ID, run_check
from connector_hub.mapping import load_mapping
from connector_hub.servicenow import ServiceNowClient

MAPPING = load_mapping(REPO / "data" / "config" / "servicenow-mapping.toml")
REPORT: dict[str, Any] = {
    "report_id": "c560bb4d0af19c72",
    "tasks": [
        {
            "task_id": "IMP-c560bb4d-SYS-001",
            "short_description": "Reassess 5 control(s) for Sample Benefits Triage Assistant",
            "description": "Rule change: example-widgets 2023-01-01 -> 2025-01-01.",
            "assignment_group": "agency-sample-benefits",
            "assigned_to": "benefits.owner@example.invalid",
            "priority": 1,
            "due_date": "2026-12-31",
            "due_date_basis": "PLACEHOLDER: level IV = 30 days (default)",
            "system_id": "SYS-001",
        },
        {
            "task_id": "IMP-c560bb4d-SYS-004",
            "short_description": "Reassess 3 control(s) for Placeholder Call-Centre Routing Model",
            "description": "Rule change.",
            "assignment_group": "dept-example-services",
            "assigned_to": "contact.owner@example.invalid",
            "priority": 4,
            "due_date": "2027-03-01",
            "due_date_basis": "PLACEHOLDER: level I = 90 days (default)",
            "system_id": "SYS-004",
        },
    ],
}


@pytest.fixture
def mock() -> Iterator[tuple[ServiceNowClient, FastAPI, TestClient]]:
    client, sn_app = mock_client()
    app_module.app.dependency_overrides[app_module.get_client] = lambda: client
    yield client, sn_app, TestClient(app_module.app)
    app_module.app.dependency_overrides.clear()


def tasks(sn_app: FastAPI) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = sn_app.state.mock.tables["u_govhub_task"]
    return rows


def test_sync_creates_then_is_idempotent(
    mock: tuple[ServiceNowClient, FastAPI, TestClient],
) -> None:
    _, sn_app, api = mock
    first = api.post("/tasks/sync-impact-report", json=REPORT).json()
    assert [t["action"] for t in first["tasks"]] == ["created", "created"]
    assert first["warnings"] == []
    row = tasks(sn_app)[0]
    assert row["correlation_id"] == "IMP-c560bb4d-SYS-001"
    assert row["correlation_display"] == "GovHub"
    assert row["u_govhub_type"] == "reassessment"
    assert row["u_govhub_reference"] == "c560bb4d0af19c72"
    assert row["priority"] == "1"
    assert row["due_date"] == "2026-12-31 23:59:59"
    assert row["state"] == "1"
    assert "PLACEHOLDER" in row["description"]
    for field in ("assignment_group", "assigned_to", "cmdb_ci"):
        assert len(row[field]) == 32  # resolved to sys_ids
    second = api.post("/tasks/sync-impact-report", json=REPORT).json()
    assert [t["action"] for t in second["tasks"]] == ["unchanged", "unchanged"]
    assert len(tasks(sn_app)) == 2


def test_resync_updates_changed_fields_but_never_reopens(
    mock: tuple[ServiceNowClient, FastAPI, TestClient],
) -> None:
    _, sn_app, api = mock
    api.post("/tasks/sync-impact-report", json=REPORT)
    row = tasks(sn_app)[0]
    row["state"] = "2"  # someone started working on it in ServiceNow
    changed = copy.deepcopy(REPORT)
    changed["tasks"][0]["due_date"] = "2027-01-15"
    result = api.post("/tasks/sync-impact-report", json=changed).json()
    assert [t["action"] for t in result["tasks"]] == ["updated", "unchanged"]
    assert row["due_date"] == "2027-01-15 23:59:59"
    assert row["state"] == "2"  # not reset to open
    assert row["work_notes"][-1] == "GovHub impact report c560bb4d0af19c72"


def test_generic_task_and_notes(mock: tuple[ServiceNowClient, FastAPI, TestClient]) -> None:
    _, sn_app, api = mock
    body = api.post(
        "/tasks",
        json={
            "correlation_id": "POAM-1234",
            "type": "remediation",
            "short_description": "Deliver telephone and in-person notices",
            "tenant": "agency-sample-benefits",
            "owner_email": "benefits.owner@example.invalid",
            "system_id": "SYS-001",
            "priority": 2,
            "due_date": "2027-01-31",
            "reference": "poam-item-uuid",
            "note": "Accepted with remediation by governance-officer-01",
        },
    ).json()
    assert body["action"] == "created" and body["number"].startswith("GOVT")
    note = api.post(
        "/tasks/POAM-1234/notes", json={"text": "Fix verified", "state": "closed_complete"}
    )
    assert note.status_code == 200
    row = tasks(sn_app)[0]
    assert (row["state"], row["work_notes"]) == (
        "3",
        ["Accepted with remediation by governance-officer-01", "Fix verified"],
    )
    assert api.post("/tasks/NOPE/notes", json={"text": "x"}).status_code == 404
    assert (
        api.post("/tasks/POAM-1234/notes", json={"text": "x", "state": "done"}).status_code == 422
    )
    bad = api.post(
        "/tasks", json={"correlation_id": "X", "type": "incident", "short_description": "x"}
    )
    assert bad.status_code == 422  # never an incident


def test_acl_denial_is_reported() -> None:
    client, _ = mock_client(username="readonly.tester")
    app_module.app.dependency_overrides[app_module.get_client] = lambda: client
    try:
        resp = TestClient(app_module.app).post("/tasks/sync-impact-report", json=REPORT)
        assert resp.status_code == 502
        assert "User Not Authorized" in resp.json()["detail"]
    finally:
        app_module.app.dependency_overrides.clear()


def test_live_check_against_mock() -> None:
    client, sn_app = mock_client()
    lines: list[str] = []
    assert run_check(client, MAPPING, lines.append) == 0
    assert any("re-run is idempotent: unchanged" in line for line in lines)
    (row,) = tasks(sn_app)
    assert (row["correlation_id"], row["state"]) == (SMOKE_ID, "3")
