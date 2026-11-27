"""Findings intake, ranked queue, placeholder identity, timed review sessions."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from review_desk_support import OFFICER, REVIEW_TABLES, VIEWER, load_report

from review_desk.models import Base


def test_every_table_is_truncated_between_tests() -> None:
    assert set(Base.metadata.tables) <= set(REVIEW_TABLES)


def test_intake_creates_placeholder_findings(
    desk: TestClient, impact_report: dict[str, Any]
) -> None:
    findings = load_report(desk, impact_report)
    assert len(findings) == impact_report["summary"]["findings_to_review"] == 20
    for f in findings:
        assert f["verdict"] == "unable-to-determine"
        assert f["confidence"] is None
        assert f["placeholder"] is True
        assert "TODO(assessment-engine)" in f["rationale"]
        assert f["state"] == "open"
    again = desk.post("/intake/impact-report", json={"report": impact_report}, headers=OFFICER)
    assert again.json() == {"report_id": impact_report["report_id"], "created": 0, "existing": 20}


def test_queue_is_ranked(desk: TestClient, impact_report: dict[str, Any]) -> None:
    findings = load_report(desk, impact_report)
    levels = [f["impact_level"] for f in findings]
    assert levels == sorted(levels, key=lambda lv: -{"IV": 4, "III": 3, "II": 2, "I": 1}[lv])
    assert [f["rank"] for f in findings] == list(range(1, 21))
    first = findings[0]
    assert (first["system_id"], first["impact_level"]) == ("SYS-001", "IV")
    # Same impact level: earlier due date first (SYS-002 overridden to 30 days, SYS-005 45).
    level_iii = [f["system_id"] for f in findings if f["impact_level"] == "III"]
    assert level_iii[:5] == ["SYS-002"] * 5 and level_iii[5:] == ["SYS-005"] * 2
    tenant = desk.get("/queue", headers=OFFICER, params={"tenant": "office-fictional-permits"})
    assert {f["system_id"] for f in tenant.json()["findings"]} == {"SYS-002", "SYS-007"}


def test_placeholder_identity(desk: TestClient, impact_report: dict[str, Any]) -> None:
    assert desk.get("/queue").status_code == 401
    assert (
        desk.post(
            "/intake/impact-report", json={"report": impact_report}, headers=VIEWER
        ).status_code
        == 403
    )
    findings = load_report(desk, impact_report)
    assert desk.get("/queue", headers=VIEWER).status_code == 200  # read-only access
    assert desk.post(f"/findings/{findings[0]['id']}/open", headers=VIEWER).status_code == 403


def test_open_starts_a_timed_session(desk: TestClient, impact_report: dict[str, Any]) -> None:
    finding = load_report(desk, impact_report)[0]
    opened = desk.post(f"/findings/{finding['id']}/open", headers=OFFICER).json()
    assert opened["finding_id"] == finding["id"]
    assert opened["session_id"] == 1
    assert desk.get(f"/findings/{finding['id']}", headers=OFFICER).json()["control_id"]
    assert desk.get("/findings/nope", headers=OFFICER).status_code == 404
