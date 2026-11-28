"""Who may call which assessment-engine endpoint; one tenant never reads another's
evidence, facts or assessments; uploaders and fact writers are recorded."""

from __future__ import annotations

from typing import Any

import pytest
from ae_support import TEST_SYSTEMS
from fastapi.testclient import TestClient

from govhub_shared.auth import GOVERNANCE_OFFICER, PLATFORM_ADMIN
from govhub_shared.auth.testing import headers, service, user

SYS = "SYS-002"  # office-fictional-permits
OTHER = "SYS-001"  # agency-sample-benefits
FACTS = {"facts": {"widgets_in_service": {"value": 2, "source": "register"}}}


def as_(who: Any) -> Any:
    return headers(who, "assessment-engine")


def permits(**roles: Any) -> Any:
    return as_(user("u-permits", **{r: ["office-fictional-permits"] for r in roles}))


def _upload(api: TestClient, system: str, who: Any = None) -> dict[str, Any]:
    resp = api.post(f"/systems/{system}/evidence", files={"file": ("e.txt", b"Notices are sent.")},
                    headers=who)  # fmt: skip
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()
    return data


def test_systems_are_in_the_expected_tenants() -> None:
    assert TEST_SYSTEMS.tenant_of(SYS) == "office-fictional-permits"
    assert TEST_SYSTEMS.tenant_of(OTHER) == "agency-sample-benefits"


def test_no_token_no_access(engine_api: TestClient) -> None:
    for path in (f"/systems/{SYS}/evidence", f"/systems/{SYS}/facts", "/evidence-policy"):
        assert engine_api.get(path, auth=None).status_code == 401, path
    assert engine_api.get("/health", auth=None).status_code == 200


def test_one_tenant_never_reads_another_tenants_evidence(engine_api: TestClient) -> None:
    theirs = _upload(engine_api, OTHER)
    reviewer = permits(reviewer=True)
    for path in (f"/systems/{OTHER}/evidence", f"/evidence/{theirs['id']}/passages",
                 f"/systems/{OTHER}/facts"):  # fmt: skip
        assert engine_api.get(path, headers=reviewer).status_code == 404, path
    search = engine_api.get(f"/systems/{OTHER}/evidence/search", params={"q": "notices"},
                            headers=reviewer)  # fmt: skip
    assert search.status_code == 404
    up = engine_api.post(f"/systems/{OTHER}/evidence", files={"file": ("x.txt", b"x")},
                         headers=reviewer)  # fmt: skip
    assert up.status_code == 404
    assert (
        engine_api.put(f"/systems/{OTHER}/facts", json=FACTS, headers=reviewer).status_code == 404
    )
    assert engine_api.get("/systems/SYS-999/evidence", headers=reviewer).status_code == 404


@pytest.mark.parametrize(
    ("roles", "metadata", "text", "write"),
    [
        ({"system_owner": True}, 200, 200, 201),
        ({"reviewer": True}, 200, 200, 201),
        ({"auditor": True}, 200, 200, 403),
        ({"tenant_admin": True}, 200, 403, 403),
    ],
)
def test_roles_within_the_tenant(
    engine_api: TestClient, roles: dict[str, bool], metadata: int, text: int, write: int
) -> None:
    doc = _upload(engine_api, SYS)
    who = permits(**roles)
    assert engine_api.get(f"/systems/{SYS}/evidence", headers=who).status_code == metadata
    assert engine_api.get(f"/evidence/{doc['id']}/passages", headers=who).status_code == text
    resp = engine_api.post(f"/systems/{SYS}/evidence", files={"file": ("n.txt", b"new")},
                           headers=who)  # fmt: skip
    assert resp.status_code == write


def test_uploaders_and_fact_writers_are_recorded_for_review_desk(engine_api: TestClient) -> None:
    _upload(engine_api, SYS, permits(system_owner=True))
    writer = as_(user("u-writer", reviewer=["office-fictional-permits"]))
    assert engine_api.put(f"/systems/{SYS}/facts", json=FACTS, headers=writer).status_code == 200
    desk = as_(service("review-desk", all_tenants=True))
    record = engine_api.get(f"/systems/{SYS}/provenance", headers=desk).json()
    assert record == {"system_id": SYS, "evidence_uploaders": ["u-permits"],
                      "fact_writers": ["u-writer"]}  # fmt: skip
    # Only review-desk asks (it decides with it); people and other services are refused.
    for who in (permits(reviewer=True), as_(service("connector-hub", all_tenants=True))):
        assert engine_api.get(f"/systems/{SYS}/provenance", headers=who).status_code == 403


def test_assessing_needs_a_reviewer_of_the_tenant(engine_api: TestClient) -> None:
    body = {"system_id": SYS, "catalog": "example-widgets", "catalog_version": "1.0.0",
            "control_ids": ["WID-6.1.2"], "as_of": "2026-12-01"}  # fmt: skip
    for who in (permits(system_owner=True), permits(auditor=True),
                as_(user("go", platform=(GOVERNANCE_OFFICER,)))):  # fmt: skip
        assert engine_api.post("/assessments", json=body, headers=who).status_code in (403, 404)
    run = engine_api.post(f"/systems/{OTHER}/assess-open-findings", json={"as_of": "2026-12-01"},
                          headers=permits(reviewer=True))  # fmt: skip
    assert run.status_code == 404


def test_drafting_and_platform_admin(engine_api: TestClient) -> None:
    reviewer = permits(reviewer=True)
    assert engine_api.post("/drafting/batches/b/draft", headers=reviewer).status_code == 403
    admin = as_(user("pa", platform=(PLATFORM_ADMIN,)))
    assert engine_api.get(f"/systems/{SYS}/evidence", headers=admin).status_code == 404
    assert engine_api.get("/evidence-policy", headers=admin).status_code == 200


def test_every_row_carries_the_systems_tenant(engine_api: TestClient, ae_engine: Any) -> None:
    from sqlalchemy import text

    _upload(engine_api, SYS)
    engine_api.put(f"/systems/{SYS}/facts", json=FACTS)
    body = {"system_id": SYS, "catalog": "example-widgets", "catalog_version": "1.0.0",
            "control_ids": ["WID-6.1.2"], "as_of": "2026-12-01"}  # fmt: skip
    assert engine_api.post("/assessments", json=body).status_code == 201
    with ae_engine.connect() as conn:
        for table in ("evidence_documents", "evidence_passages", "system_facts", "assessments",
                      "assessment_results_documents"):  # fmt: skip
            tenants = set(conn.scalars(text(f"SELECT DISTINCT tenant FROM {table}")))  # noqa: S608
            assert tenants == {"office-fictional-permits"}, table


def test_backfill_sets_the_tenant_of_old_rows(engine_api: TestClient, ae_engine: Any,
                                              ae_database_url: str) -> None:  # fmt: skip
    from sqlalchemy import text

    from assessment_engine.backfill import backfill

    _upload(engine_api, SYS)
    body = {"system_id": SYS, "catalog": "example-widgets", "catalog_version": "1.0.0",
            "control_ids": ["WID-6.1.2"], "as_of": "2026-12-01"}  # fmt: skip
    engine_api.post("/assessments", json=body)
    with ae_engine.begin() as conn:  # as stored before Milestone 7
        for table in ("evidence_documents", "evidence_passages", "assessments"):
            conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
            conn.execute(text(f"UPDATE {table} SET tenant = NULL"))  # noqa: S608
            conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
    counts = backfill(ae_database_url, TEST_SYSTEMS)
    assert counts["evidence_documents"] == 1 and counts["assessments"] == 1
    with ae_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM assessments WHERE tenant IS NULL")) == 0
        # The immutability trigger is back on.
        with pytest.raises(Exception, match="immutable"):
            conn.execute(text("UPDATE assessments SET verdict = 'met'"))
