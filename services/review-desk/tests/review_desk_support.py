"""Shared constants and helpers for review-desk tests (unique module name on purpose)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from govhub_shared.auth import GOVERNANCE_OFFICER
from govhub_shared.auth.testing import headers, service, user

FIXTURES = Path(__file__).parent / "fixtures"
# Every review-desk table; a test fails if a new table is missing (no leaks between tests).
REVIEW_TABLES = ("findings", "review_sessions", "decision_log", "poam_versions")
DEMO_TENANTS = ["agency-sample-benefits", "dept-example-services", "office-fictional-permits"]
# Decisions are recorded by reviewers of the finding's tenant. "OFFICER" (historic name in
# these tests) is a governance officer who also reviews in every demo tenant.
OFFICER = headers(
    user("governance-officer-01", platform=(GOVERNANCE_OFFICER,), reviewer=DEMO_TENANTS),
    "review-desk",
)
REVIEWER = headers(user("reviewer-02", reviewer=DEMO_TENANTS), "review-desk")
VIEWER = headers(user("viewer-03", auditor=DEMO_TENANTS), "review-desk")  # reads, never decides
ENGINE = headers(service("assessment-engine", all_tenants=True), "review-desk")


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
