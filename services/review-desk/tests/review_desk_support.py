"""Shared constants and helpers for review-desk tests (unique module name on purpose)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"
# Every review-desk table; a test fails if a new table is missing (no leaks between tests).
REVIEW_TABLES = ("findings", "review_sessions", "decision_log")
OFFICER = {"X-GovHub-User": "governance-officer-01", "X-GovHub-Role": "governance-officer"}
REVIEWER = {"X-GovHub-User": "reviewer-02", "X-GovHub-Role": "reviewer"}
VIEWER = {"X-GovHub-User": "viewer-03", "X-GovHub-Role": "viewer"}


def load_report(desk: TestClient, report: dict[str, Any]) -> list[dict[str, Any]]:
    resp = desk.post("/intake/impact-report", json={"report": report}, headers=OFFICER)
    assert resp.status_code == 200, resp.json()
    findings: list[dict[str, Any]] = desk.get(
        "/queue", headers=OFFICER, params={"limit": 1000}
    ).json()["findings"]
    return findings


def decide(
    desk: TestClient, finding_id: str, body: dict[str, Any], headers: dict[str, str] = OFFICER
) -> Any:
    return desk.post(f"/findings/{finding_id}/decisions", json=body, headers=headers)
