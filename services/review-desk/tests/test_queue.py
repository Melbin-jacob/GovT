"""Findings intake, ranked queue, placeholder identity, timed review sessions."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from review_desk_support import ENGINE, OFFICER, REVIEW_TABLES, VIEWER, decide, load_report

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


def test_identity_from_internal_tokens(desk: TestClient, impact_report: dict[str, Any]) -> None:
    assert desk.get("/queue", auth=None).status_code == 401
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


def _draft(**overrides: Any) -> dict[str, Any]:
    return {
        "assessment_id": "a-1",
        "run_id": "r-1",
        "method": "model",
        "verdict": "partially-met",
        "confidence": 0.82,
        "rationale": {"en": "Online only.", "fr": "En ligne seulement."},
        "model_id": "qwen3-8b",
        "prompt_version": "assess-v1",
        "cited_passage_id": "doc:2",
        "cited_quote": "No notice is given by telephone",
        "evidence_language": "en",
        "flagged_passage_ids": [],
        **overrides,
    }


def test_engine_draft_replaces_the_placeholder_but_keeps_the_finding_open(
    desk: TestClient, impact_report: dict[str, Any]
) -> None:
    finding = load_report(desk, impact_report)[0]
    resp = desk.put(f"/findings/{finding['id']}/assessment", json=_draft(), headers=ENGINE)
    assert resp.status_code == 200, resp.json()
    view = resp.json()
    assert (view["verdict"], view["confidence"], view["placeholder"]) == (
        "partially-met",
        0.82,
        False,
    )
    assert view["state"] == finding["state"]  # never closed by the engine
    assert view["assessment"]["cited_quote"] == "No notice is given by telephone"
    assert view["rationale"] == "Online only."


def test_only_the_engine_may_post_drafts_and_never_on_decided_findings(
    desk: TestClient, impact_report: dict[str, Any]
) -> None:
    finding = load_report(desk, impact_report)[0]
    url = f"/findings/{finding['id']}/assessment"
    assert desk.put(url, json=_draft(), headers=OFFICER).status_code == 403
    assert desk.put(url, json=_draft(verdict="compliant"), headers=ENGINE).status_code == 422
    decide(desk, finding["id"], {"action": "accept", "annotation": "ok"})
    assert desk.put(url, json=_draft(), headers=ENGINE).status_code == 409
