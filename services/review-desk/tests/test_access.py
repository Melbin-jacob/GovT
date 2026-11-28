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


class FakeProvenance:
    def __init__(self, uploaders: list[str], writers: list[str], down: bool = False) -> None:
        self.record = {"evidence_uploaders": uploaders, "fact_writers": writers}
        self.down = down
        self.asked: list[str] = []

    def of(self, system_id: str) -> dict[str, Any]:
        from review_desk.provenance import ProvenanceUnavailableError

        self.asked.append(system_id)
        if self.down:
            raise ProvenanceUnavailableError("engine unreachable")
        return {"system_id": system_id, **self.record}


def _with_provenance(fake: FakeProvenance) -> None:
    from review_desk.app import app, get_provenance

    app.dependency_overrides[get_provenance] = lambda: fake


def test_conflict_of_interest_evidence_uploader(
    desk: TestClient, impact_report: dict[str, Any]
) -> None:
    mine, _ = _split(load_report(desk, impact_report))
    fake = FakeProvenance(uploaders=["rv"], writers=[])
    _with_provenance(fake)
    resp = decide(desk, mine["id"], ACCEPT, headers=as_(user("rv", reviewer=[PERMITS])))
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "conflict-of-interest" and detail["reasons"] == ["uploaded-evidence"]
    assert fake.asked == [mine["system_id"]]
    # Another reviewer of the tenant, who supplied nothing, may decide.
    other = decide(desk, mine["id"], ACCEPT, headers=as_(user("rv2", reviewer=[PERMITS])))
    assert other.status_code == 200


def test_conflict_of_interest_fact_writer_and_both(
    desk: TestClient, impact_report: dict[str, Any]
) -> None:
    mine, _ = _split(load_report(desk, impact_report))
    _with_provenance(FakeProvenance(uploaders=["rv"], writers=["rv", "so"]))
    detail = decide(desk, mine["id"], ACCEPT, headers=as_(user("rv", reviewer=[PERMITS]))).json()
    assert detail["detail"]["reasons"] == ["uploaded-evidence", "wrote-facts"]
    _with_provenance(FakeProvenance(uploaders=[], writers=["rv"]))
    detail = decide(desk, mine["id"], ACCEPT, headers=as_(user("rv", reviewer=[PERMITS]))).json()
    assert detail["detail"]["reasons"] == ["wrote-facts"]


def test_conflict_check_fails_closed(desk: TestClient, impact_report: dict[str, Any]) -> None:
    mine, _ = _split(load_report(desk, impact_report))
    _with_provenance(FakeProvenance([], [], down=True))
    resp = decide(desk, mine["id"], ACCEPT, headers=as_(user("rv", reviewer=[PERMITS])))
    assert resp.status_code == 503 and resp.json()["detail"]["code"] == "provenance-unavailable"
    assert desk.get(f"/findings/{mine['id']}/decisions").json() == []  # nothing recorded


def test_tenant_columns_follow_the_finding(
    desk: TestClient, impact_report: dict[str, Any], review_engine: Any
) -> None:
    from sqlalchemy import text

    mine, _ = _split(load_report(desk, impact_report))
    reviewer = as_(user("rv", reviewer=[PERMITS]))
    opened = desk.post(f"/findings/{mine['id']}/open", headers=reviewer).json()
    remediate = {"action": "accept-with-remediation", "annotation": "Needs a fix.",
                 "remediation": {"description": "Fix it.", "due_date": "2027-01-31"},
                 "session_id": opened["session_id"]}  # fmt: skip
    assert decide(desk, mine["id"], remediate, headers=reviewer).status_code == 200
    with review_engine.connect() as conn:
        for table in ("review_sessions", "poam_versions", "decision_log"):
            got = set(conn.scalars(text(f"SELECT DISTINCT tenant FROM {table}")))  # noqa: S608
            assert got == {PERMITS}, table
        # The decision log's tenant is generated from the record itself, never written.
        generated = conn.scalar(text(
            "SELECT attgenerated FROM pg_attribute WHERE attrelid = 'decision_log'::regclass "
            "AND attname = 'tenant'"
        ))  # fmt: skip
        assert generated == "s"
