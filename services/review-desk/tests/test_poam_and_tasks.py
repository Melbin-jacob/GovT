"""Decision side effects: OSCAL POA&M items and ServiceNow tasks through connector-hub.

Wiring is in-process: review-desk -> connector-hub app -> mock ServiceNow.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mock_support import mock_client
from review_desk_support import OFFICER, decide, load_report
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from connector_hub import app as connector_module
from govhub_shared.oscal import validate
from review_desk.app import app as desk_app
from review_desk.app import get_task_sink
from review_desk.tasks import HttpTaskSink

REMEDIATE = {
    "action": "accept-with-remediation",
    "annotation": "Register lacks the firmware version field.",
    "remediation": {
        "description": "Add firmware version to the widget register.",
        "due_date": "2027-01-31",
    },
}


@pytest.fixture
def servicenow(desk: TestClient, impact_report: dict[str, Any]) -> Iterator[FastAPI]:
    """Connector-hub backed by the mock; impact-report tasks already synced; review-desk's
    task sink pointed at connector-hub."""
    client, sn_app = mock_client()
    connector_module.app.dependency_overrides[connector_module.get_client] = lambda: client
    connector = TestClient(connector_module.app)
    synced = connector.post("/tasks/sync-impact-report", json=impact_report).json()
    assert all(t["action"] == "created" for t in synced["tasks"])
    desk_app.dependency_overrides[get_task_sink] = lambda: HttpTaskSink("", http=connector)
    yield sn_app
    connector_module.app.dependency_overrides.clear()
    desk_app.dependency_overrides.pop(get_task_sink, None)


def _tasks(sn_app: FastAPI, kind: str) -> list[dict[str, Any]]:
    return [t for t in sn_app.state.mock.tables["u_govhub_task"] if t.get("u_govhub_type") == kind]


def test_remediation_creates_poam_item_and_task(
    desk: TestClient, impact_report: dict[str, Any], servicenow: FastAPI
) -> None:
    finding = next(f for f in load_report(desk, impact_report) if f["control_id"] == "WID-6.1.2")
    body = decide(desk, finding["id"], REMEDIATE).json()
    effects = body["side_effects"]
    assert effects["remediation-task"]["status"] == "sent"
    assert effects["remediation-task"]["number"].startswith("GOVT")
    assert effects["work-note"] == "sent"
    assert effects["poam"]["version"] == 1

    (task,) = _tasks(servicenow, "remediation")
    assert task["correlation_id"] == f"POAM-{effects['poam']['item-uuid']}"
    assert task["due_date"] == "2027-01-31 23:59:59"
    assert task["u_govhub_reference"] == effects["poam"]["item-uuid"]
    reassessment = next(
        t for t in _tasks(servicenow, "reassessment") if t["correlation_id"] == finding["task_id"]
    )
    decision_note, checkpoint_note = reassessment["work_notes"][-2:]
    assert "WID-6.1.2: accept-with-remediation by governance-officer-01" in decision_note
    assert (
        checkpoint_note == f"GovHub decision-log checkpoint seq=1 head={body['log']['record_hash']}"
    )

    doc = desk.get(f"/poam/{finding['system_id']}", headers=OFFICER).json()
    validate(doc, "plan-of-action-and-milestones")
    poam = doc["plan-of-action-and-milestones"]
    assert poam["system-id"] == {
        "identifier-type": "https://egcsgroup.com/ns/oscal",
        "id": finding["system_id"],
    }
    (item,) = poam["poam-items"]
    assert item["uuid"] == effects["poam"]["item-uuid"]
    props = {p["name"]: p["value"] for p in item["props"]}
    assert props["control-id"] == "WID-6.1.2"
    assert props["servicenow-task"] == effects["remediation-task"]["number"]
    (risk,) = poam["risks"]
    assert risk["deadline"].startswith("2027-01-31T23:59:59")
    assert risk["remediations"][0]["description"] == REMEDIATE["remediation"]["description"]
    (oscal_finding,) = poam["findings"]
    assert oscal_finding["target"]["status"] == {"state": "not-satisfied", "reason": "other"}
    assert "implementation-status" not in oscal_finding["target"]  # unable-to-determine


def test_poam_versions_accumulate_and_are_immutable(
    desk: TestClient, impact_report: dict[str, Any], servicenow: FastAPI, review_db: Session
) -> None:
    sys1 = [f for f in load_report(desk, impact_report) if f["system_id"] == "SYS-001"]
    decide(desk, sys1[0]["id"], REMEDIATE)
    decide(desk, sys1[1]["id"], REMEDIATE)
    latest = desk.get("/poam/SYS-001", headers=OFFICER).json()["plan-of-action-and-milestones"]
    first = desk.get("/poam/SYS-001", headers=OFFICER, params={"version": 1}).json()
    assert latest["metadata"]["version"] == "2" and len(latest["poam-items"]) == 2
    assert len(first["plan-of-action-and-milestones"]["poam-items"]) == 1
    assert desk.get("/poam", headers=OFFICER).json() == [
        {"system_id": "SYS-001", "version": 2, "items": 2}
    ]
    with pytest.raises(DBAPIError, match="append-only"):
        review_db.execute(text("UPDATE poam_versions SET version = 9"))
    review_db.rollback()
    assert desk.get("/poam/SYS-404", headers=OFFICER).status_code == 404


def test_evidence_request_task(
    desk: TestClient, impact_report: dict[str, Any], servicenow: FastAPI
) -> None:
    finding = load_report(desk, impact_report)[0]
    body = decide(
        desk,
        finding["id"],
        {"action": "request-more-evidence", "annotation": "Attach the 2026 log."},
    ).json()
    assert body["side_effects"]["evidence-task"]["status"] == "sent"
    (task,) = _tasks(servicenow, "evidence-request")
    assert task["correlation_id"] == f"EVID-{finding['id']}"
    assert "Attach the 2026 log." in task["description"]
    assert "evidence" not in body["side_effects"].get("poam", {})


def test_decisions_are_logged_even_without_connector(
    desk: TestClient, impact_report: dict[str, Any]
) -> None:
    finding = load_report(desk, impact_report)[0]
    body = decide(desk, finding["id"], REMEDIATE).json()  # default sink: not configured
    assert body["side_effects"]["remediation-task"]["status"].startswith("not sent")
    assert body["side_effects"]["poam"]["version"] == 1  # POA&M is local, always recorded
    record = desk.get(f"/findings/{finding['id']}/decisions", headers=OFFICER).json()[0]
    assert record["side-effects"]["remediation-task"]["status"].startswith("not sent")
    assert desk.get("/decision-log/verify", headers=OFFICER).json()["ok"] is True
