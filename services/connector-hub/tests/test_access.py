"""Who may call which connector-hub endpoint (internal tokens)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from connector_hub.app import app
from govhub_shared.auth import GOVERNANCE_OFFICER, PLATFORM_ADMIN
from govhub_shared.auth.testing import headers, service, user

PERMITS = ["office-fictional-permits"]


def as_(who: Any) -> Any:
    return headers(who, "connector-hub")


@pytest.mark.parametrize(
    ("method", "path", "who", "status"),
    [
        ("POST", "/inventory/sync", user("rv", reviewer=PERMITS), 403),
        ("POST", "/inventory/sync", user("pa", platform=(PLATFORM_ADMIN,)), 403),
        ("POST", "/tasks/sync-impact-report", user("rv", reviewer=PERMITS), 403),
        ("POST", "/tasks", user("go", platform=(GOVERNANCE_OFFICER,)), 403),
        ("POST", "/tasks/X/notes", user("ta", tenant_admin=PERMITS), 403),
        ("POST", "/tasks", service("assessment-engine", all_tenants=True), 403),
        ("GET", "/tasks/notes", user("so", system_owner=PERMITS), 403),
    ],
)
def test_refusals(method: str, path: str, who: Any, status: int) -> None:
    client = TestClient(app)
    assert client.request(method, path, json={}, headers=as_(who)).status_code == status


def test_no_token_and_wrong_audience() -> None:
    client = TestClient(app)
    assert client.get("/tasks/notes").status_code == 401
    wrong = headers(user("rv", reviewer=PERMITS), "review-desk")
    assert client.get("/tasks/notes", headers=wrong).json()["detail"]["code"] == "audience"
    assert client.get("/health").status_code == 200
