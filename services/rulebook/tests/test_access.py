"""Who may call which rulebook endpoint (internal tokens; docs/access-matrix.md)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_impact import REQUEST, seed

from govhub_shared.auth import GOVERNANCE_OFFICER, PLATFORM_ADMIN
from govhub_shared.auth.testing import headers, service, user

PERMITS = "office-fictional-permits"
BENEFITS = "agency-sample-benefits"


def as_(who: Any) -> Any:
    return headers(who, "rulebook")


def test_no_token_no_access(client: TestClient) -> None:
    for path in ("/catalogs", "/inventory", "/profiles", "/sources", "/drafts/batches"):
        resp = client.get(path, auth=None)
        assert resp.status_code == 401, path
        assert resp.json()["detail"]["code"] == "no-token"
    assert client.get("/health", auth=None).status_code == 200


def test_a_token_for_another_service_is_refused(client: TestClient) -> None:
    resp = client.get("/catalogs", headers=headers(user("u", reviewer=[PERMITS]), "review-desk"))
    assert resp.status_code == 401 and resp.json()["detail"]["code"] == "audience"


def test_platform_admin_has_no_data_access(client: TestClient) -> None:
    seed(client)
    admin = as_(user("pa", platform=(PLATFORM_ADMIN,)))
    for path in ("/catalogs", "/inventory", "/sources", "/profiles"):
        assert client.get(path, headers=admin).status_code == 403, path
    assert client.post("/impact-reports", json=REQUEST, headers=admin).status_code == 403


def test_only_governance_officers_change_shared_content(client: TestClient) -> None:
    seed(client)
    reviewer = as_(user("rv", reviewer=[PERMITS], tenant_admin=[PERMITS]))
    doc = client.get("/catalogs/example-widgets/versions/1.0.0").json()
    resp = client.post("/catalogs", json=doc, headers=reviewer)
    assert resp.status_code == 403 and resp.json()["detail"]["code"] == "role"
    retire = "/catalogs/example-widgets/versions/1.0.0/retire-control/WID-6.3.2"
    assert client.post(retire, headers=reviewer).status_code == 403
    assert client.post("/sources", json={}, headers=reviewer).status_code == 403
    officer = as_(user("go", platform=(GOVERNANCE_OFFICER,)))
    assert client.post(retire, headers=officer).status_code == 201


def test_inventory_shows_only_the_callers_tenants(client: TestClient) -> None:
    seed(client)
    permits = as_(user("rv", reviewer=[PERMITS]))
    systems = client.get("/inventory", headers=permits).json()["systems"]
    assert {s["tenant"] for s in systems} == {PERMITS} and len(systems) == 2
    other = next(s for s in client.get("/inventory").json()["systems"] if s["tenant"] == BENEFITS)
    assert client.get(f"/systems/{other['system_id']}", headers=permits).status_code == 404
    mine = systems[0]["system_id"]
    assert client.get(f"/systems/{mine}", headers=permits).json()["tenant"] == PERMITS
    # Asking for another tenant by name gives nothing either.
    resp = client.get("/inventory", params={"tenant": BENEFITS}, headers=permits)
    assert resp.json()["systems"] == []


def test_impact_reports_leave_out_other_tenants(client: TestClient) -> None:
    seed(client)
    full = client.post("/impact-reports", json=REQUEST).json()
    assert {s["tenant"] for s in full["systems"]} > {PERMITS}
    permits = client.post(
        "/impact-reports", json=REQUEST, headers=as_(user("rv", reviewer=[PERMITS]))
    ).json()
    assert {s["tenant"] for s in permits["systems"]} == {PERMITS}
    shown = {e["system_id"] for e in permits["excluded_systems"]} | {
        s["system_id"] for s in permits["systems"]
    }
    others = {s["system_id"] for s in full["systems"] if s["tenant"] != PERMITS}
    assert not shown & others  # not even listed as excluded
    assert permits["affected_controls"] == full["affected_controls"]  # shared content
    officer = client.post(
        "/impact-reports", json=REQUEST, headers=as_(user("go", platform=(GOVERNANCE_OFFICER,)))
    ).json()
    assert officer["systems"] == [] and officer["affected_controls"]


def test_only_the_sync_job_replaces_the_inventory(client: TestClient) -> None:
    seed(client)
    snapshot = {"source": "x", "systems": client.get("/inventory").json()["systems"]}
    admin = as_(user("ta", tenant_admin=[PERMITS, BENEFITS]))
    assert client.put("/inventory", json=snapshot, headers=admin).status_code == 403
    narrow = as_(service("connector-hub"))
    resp = client.put("/inventory", json=snapshot, headers=narrow)
    assert resp.status_code == 403 and resp.json()["detail"]["code"] == "scope"
    engine = as_(service("assessment-engine", all_tenants=True))
    assert client.put("/inventory", json=snapshot, headers=engine).status_code == 403
    sync = as_(service("connector-hub", all_tenants=True))
    assert client.put("/inventory", json=snapshot, headers=sync).status_code == 201


def test_tenant_admin_chooses_profiles_for_own_systems(client: TestClient) -> None:
    seed(client)
    systems = client.get("/inventory").json()["systems"]
    mine = next(s for s in systems if s["tenant"] == PERMITS)
    theirs = next(s for s in systems if s["tenant"] == BENEFITS)
    admin = as_(user("ta", tenant_admin=[PERMITS]))
    before = client.post("/impact-reports", json=REQUEST).json()
    assert "profile_assignments_hash" not in before["inputs"]

    resp = client.put(f"/systems/{mine['system_id']}/profiles", json={"profiles": []},
                      headers=admin)  # fmt: skip
    assert resp.status_code == 200 and resp.json()["set_by"] == "ta"
    after = client.post("/impact-reports", json=REQUEST).json()
    assert mine["system_id"] not in {s["system_id"] for s in after["systems"]}
    excluded = {e["system_id"]: e["code"] for e in after["excluded_systems"]}
    assert excluded[mine["system_id"]] == "no-profile"
    assert after["inputs"]["profile_assignments_hash"] and after["report_id"] != before["report_id"]
    shown = client.get(f"/systems/{mine['system_id']}").json()
    assert shown["profiles"] == []

    # Another tenant's system: not even visible. Other roles: refused.
    other = client.put(f"/systems/{theirs['system_id']}/profiles", json={"profiles": []},
                       headers=admin)  # fmt: skip
    assert other.status_code == 404
    reviewer = as_(user("rv", reviewer=[PERMITS]))
    refused = client.put(f"/systems/{mine['system_id']}/profiles", json={"profiles": []},
                         headers=reviewer)  # fmt: skip
    assert refused.status_code == 403
    unknown = client.put(f"/systems/{mine['system_id']}/profiles",
                         json={"profiles": ["no-such-profile"]}, headers=admin)  # fmt: skip
    assert unknown.status_code == 422


@pytest.mark.parametrize(
    ("who", "status"),
    [
        (user("au", auditor=[PERMITS]), 200),
        (user("rv", reviewer=[PERMITS]), 200),
        (user("so", system_owner=[PERMITS]), 403),
        (service("assessment-engine"), 200),
        (service("connector-hub", all_tenants=True), 403),
    ],
)
def test_who_reads_drafting_batches(client: TestClient, who: Any, status: int) -> None:
    assert client.get("/drafts/batches", headers=as_(who)).status_code == status


def test_auditors_read_the_approval_log_but_do_not_edit(client: TestClient) -> None:
    auditor = as_(user("au", auditor=[PERMITS]))
    assert client.get("/drafts/log/verify", headers=auditor).status_code == 200
    assert client.get("/drafts/log/export", headers=auditor).status_code == 200
    assert client.post("/drafts/sessions", headers=auditor).status_code == 403
    assert client.post("/drafts/batches", json={}, headers=auditor).status_code == 403
