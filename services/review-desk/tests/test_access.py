"""Who may call which review-desk endpoint, and one tenant never sees another's findings."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient
from review_desk_support import decide, load_report

from govhub_shared.auth import GOVERNANCE_OFFICER
from govhub_shared.auth.testing import headers, service, user

PERMITS = "office-fictional-permits"
ACCEPT = {"action": "accept", "annotation": "Evidence is sufficient."}


def as_(who: Any) -> Any:
    return headers(who, "review-desk")


def _split(findings: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    mine = next(f for f in findings if f["tenant"] == PERMITS)
    theirs = next(f for f in findings if f["tenant"] != PERMITS)
    return mine, theirs


def test_one_tenant_never_sees_another_tenants_findings(
    desk: TestClient, impact_report: dict[str, Any]
) -> None:
    mine, theirs = _split(load_report(desk, impact_report))
    permits = as_(user("rv", reviewer=[PERMITS]))
    queue = desk.get("/queue", headers=permits, params={"limit": 1000}).json()
    assert {f["tenant"] for f in queue["findings"]} == {PERMITS}
    assert desk.get(f"/findings/{theirs['id']}", headers=permits).status_code == 404
    assert desk.get(f"/findings/{theirs['id']}/decisions", headers=permits).status_code == 404
    assert desk.post(f"/findings/{theirs['id']}/open", headers=permits).status_code == 404
    assert decide(desk, theirs["id"], ACCEPT, headers=permits).status_code == 404
    assert desk.get(f"/findings/{mine['id']}", headers=permits).status_code == 200
    # POA&Ms: only systems of the caller's tenants.
    assert decide(desk, theirs["id"], ACCEPT).status_code == 200  # someone allowed
    assert desk.get("/poam", headers=permits).json() == []
    assert desk.get(f"/poam/{theirs['system_id']}", headers=permits).status_code == 404


def test_only_a_reviewer_of_the_findings_tenant_decides(
    desk: TestClient, impact_report: dict[str, Any]
) -> None:
    mine, _ = _split(load_report(desk, impact_report))
    for who in (
        user("go", platform=(GOVERNANCE_OFFICER,)),  # platform role: no tenant
        user("au", auditor=[PERMITS]),
        user("ta", tenant_admin=[PERMITS]),
        user("so", system_owner=[PERMITS]),
    ):
        assert decide(desk, mine["id"], ACCEPT, headers=as_(who)).status_code in (403, 404), who
    reviewer = as_(user("rv", reviewer=[PERMITS]))
    opened = desk.post(f"/findings/{mine['id']}/open", headers=reviewer).json()
    body = {**ACCEPT, "session_id": opened["session_id"]}
    done = decide(desk, mine["id"], body, headers=reviewer)
    assert done.status_code == 200
    record = desk.get(f"/findings/{mine['id']}/decisions", headers=reviewer).json()[0]
    assert record["reviewer"] == {"id": "rv", "role": "reviewer", "authorized": True}


def test_auditors_read_their_tenants_log_and_never_decide(
    desk: TestClient, impact_report: dict[str, Any]
) -> None:
    mine, theirs = _split(load_report(desk, impact_report))
    assert decide(desk, mine["id"], ACCEPT).status_code == 200
    assert decide(desk, theirs["id"], ACCEPT).status_code == 200
    auditor = as_(user("au", auditor=[PERMITS]))
    lines = [json.loads(line) for line in
             desk.get("/decision-log/export", headers=auditor).text.splitlines() if line]  # fmt: skip
    tenants = {json.loads(line["record"])["tenant"] for line in lines}
    assert tenants == {PERMITS}
    assert desk.get("/decision-log/verify", headers=auditor).json()["ok"] is True
    assert desk.post(f"/findings/{mine['id']}/open", headers=auditor).status_code == 403
    owner = as_(user("so", system_owner=[PERMITS]))
    assert desk.get("/decision-log/export", headers=owner).status_code == 403


def test_assessment_drafts_only_from_the_engine(
    desk: TestClient, impact_report: dict[str, Any]
) -> None:
    mine, _ = _split(load_report(desk, impact_report))
    draft = {"assessment_id": "a1", "run_id": "r1", "method": "rule", "verdict": "met",
             "confidence": 1.0, "rationale": {"en": "x", "fr": "x"}}  # fmt: skip
    path = f"/findings/{mine['id']}/assessment"
    reviewer = as_(user("rv", reviewer=[PERMITS]))
    assert desk.put(path, json=draft, headers=reviewer).status_code == 403
    assert desk.put(path, json=draft, headers=as_(service("connector-hub"))).status_code == 403
    engine = as_(service("assessment-engine", all_tenants=True))
    assert desk.put(path, json=draft, headers=engine).status_code == 200


def test_intake_and_tokens(desk: TestClient, impact_report: dict[str, Any]) -> None:
    body = {"report": impact_report}
    reviewer = as_(user("rv", reviewer=[PERMITS]))
    assert desk.post("/intake/impact-report", json=body, headers=reviewer).status_code == 403
    officer = as_(user("go", platform=(GOVERNANCE_OFFICER,)))
    assert desk.post("/intake/impact-report", json=body, headers=officer).status_code == 200
    assert desk.get("/queue", auth=None).status_code == 401
    wrong = headers(user("rv", reviewer=[PERMITS]), "rulebook")
    assert desk.get("/queue", headers=wrong).json()["detail"]["code"] == "audience"
    assert desk.get("/health", auth=None).status_code == 200
