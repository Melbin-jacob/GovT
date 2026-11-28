"""Row-level security: through the app role, one tenant never reads or writes another's
findings, review sessions, decision-log records or POA&Ms, even where application code
forgets to filter. Requests run with sessions logged in as a non-owner role, as in a
deployment (the other tests use the owner, which RLS does not bind)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from review_desk_support import DEMO_TENANTS, REVIEW_TABLES, load_report
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from govhub_shared import tenancy
from govhub_shared.auth.testing import headers, user
from govhub_shared.rls_testing import (
    app_role_engine,
    owner_tenants,
    rls_enabled,
    session,
    tenants_seen,
    unbound_session,
)
from review_desk import decision_log
from review_desk.app import app
from review_desk.db import get_session

PERMITS = "office-fictional-permits"
OTHER = "agency-sample-benefits"
REMEDIATE = {"action": "accept-with-remediation", "annotation": "Needs a fix.",
             "remediation": {"description": "Fix it.", "due_date": "2027-01-31"}}  # fmt: skip


def reviewer_of(tenant: str) -> dict[str, str]:
    return dict(headers(user(f"rv-{tenant}", reviewer=[tenant]), "review-desk"))


@pytest.fixture(scope="session")
def app_engine(review_engine: Engine) -> Iterator[Engine]:
    engine = app_role_engine(review_engine)
    yield engine
    engine.dispose()


@pytest.fixture
def desk_rls(desk: TestClient, app_engine: Engine) -> TestClient:
    """The review-desk API with every request's session logged in as the app role."""
    factory = sessionmaker(bind=app_engine, expire_on_commit=False)

    def _session() -> Iterator[Session]:
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    return desk


@pytest.fixture
def populated(desk_rls: TestClient, impact_report: dict[str, Any]) -> list[dict[str, Any]]:
    """Through the app role: intake (a governance officer, platform-wide), then one timed
    decision with a POA&M item in every tenant, alternating tenants on the one chain."""
    findings = load_report(desk_rls, impact_report)
    for tenant in sorted({f["tenant"] for f in findings}):
        finding = next(f for f in findings if f["tenant"] == tenant)
        who = reviewer_of(tenant)
        opened = desk_rls.post(f"/findings/{finding['id']}/open", headers=who)
        assert opened.status_code == 200, opened.text
        body = {**REMEDIATE, "session_id": opened.json()["session_id"]}
        done = desk_rls.post(f"/findings/{finding['id']}/decisions", json=body, headers=who)
        assert done.status_code == 200, done.text
    return findings


def test_every_tenant_table_has_row_level_security(review_engine: Engine) -> None:
    with review_engine.connect() as conn:
        with_tenant = set(conn.scalars(text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'tenant'")))  # fmt: skip
    assert with_tenant == set(REVIEW_TABLES)
    for table in REVIEW_TABLES:
        assert rls_enabled(review_engine, table) == (True, False), table  # enabled, not forced


def test_an_unbound_connection_sees_nothing(
    populated: list[dict[str, Any]], review_engine: Engine, app_engine: Engine
) -> None:
    for table in REVIEW_TABLES:
        assert sum(owner_tenants(review_engine, table).values()) > 0, table
        with unbound_session(app_engine) as s:
            assert s.scalar(text(f"SELECT count(*) FROM {table}")) == 0, table  # noqa: S608
        assert tenants_seen(app_engine, table, tenancy.NO_TENANTS) == {}, table


def test_a_bound_connection_sees_only_its_tenants(
    populated: list[dict[str, Any]], review_engine: Engine, app_engine: Engine
) -> None:
    for table in REVIEW_TABLES:
        owner = owner_tenants(review_engine, table)
        assert set(owner) == set(DEMO_TENANTS), table
        assert tenants_seen(app_engine, table, frozenset({PERMITS})) == {PERMITS: owner[PERMITS]}
        two = frozenset({PERMITS, OTHER})
        assert tenants_seen(app_engine, table, two) == {t: owner[t] for t in two}
        assert tenants_seen(app_engine, table, tenancy.ALL_TENANTS) == owner, table


def test_writes_into_another_tenant_are_refused(
    populated: list[dict[str, Any]], app_engine: Engine
) -> None:
    mine = next(f for f in populated if f["tenant"] == PERMITS)
    theirs = next(f for f in populated if f["tenant"] == OTHER)
    scope = frozenset({PERMITS})
    # Moving a row out of the caller's tenants (findings, review sessions).
    for table, key in (("findings", "id"), ("review_sessions", "finding_id")):
        with session(app_engine, scope) as s, pytest.raises(ProgrammingError, match="row-level"):
            s.execute(text(f"UPDATE {table} SET tenant = :o WHERE {key} = :f"),  # noqa: S608
                      {"o": OTHER, "f": mine["id"]})  # fmt: skip
    # Another tenant's rows are invisible to UPDATE and DELETE (nothing happens).
    with session(app_engine, scope) as s:
        hit = s.execute(text("UPDATE findings SET state = 'closed' WHERE id = :f"),
                        {"f": theirs["id"]})  # fmt: skip
        assert hit.rowcount == 0  # type: ignore[attr-defined]
        gone = s.execute(text("DELETE FROM review_sessions WHERE tenant = :o"), {"o": OTHER})
        assert gone.rowcount == 0  # type: ignore[attr-defined]
        s.rollback()
    # A decision record for another tenant, even though the chain head is read across
    # tenants (the insert is still checked).
    record = {"uuid": str(uuid.uuid4()), "finding-uuid": theirs["id"], "action": "accept",
              "tenant": OTHER}  # fmt: skip
    with session(app_engine, scope) as s, pytest.raises(ProgrammingError, match="row-level"):
        decision_log.append(s, record)


def test_the_api_through_the_app_role_keeps_tenants_apart(
    populated: list[dict[str, Any]], desk_rls: TestClient
) -> None:
    permits = reviewer_of(PERMITS)
    theirs = next(f for f in populated if f["tenant"] == OTHER)
    queue = desk_rls.get("/queue", headers=permits, params={"limit": 1000}).json()
    assert {f["tenant"] for f in queue["findings"]} == {PERMITS}
    assert desk_rls.get(f"/findings/{theirs['id']}", headers=permits).status_code == 404
    assert desk_rls.get(f"/poam/{theirs['system_id']}", headers=permits).status_code == 404
    assert {p["system_id"] for p in desk_rls.get("/poam", headers=permits).json()} <= {
        f["system_id"] for f in populated if f["tenant"] == PERMITS
    }
    export = desk_rls.get("/decision-log/export", headers=permits).text.splitlines()
    assert {json.loads(json.loads(line)["record"])["tenant"] for line in export} == {PERMITS}


def test_one_chain_still_verifies_through_the_app_role(
    populated: list[dict[str, Any]], desk_rls: TestClient, review_engine: Engine
) -> None:
    """Decisions in alternating tenants each linked to the true head (read across tenants);
    verification and checkpoints cover the whole chain but return only counts and hashes."""
    with review_engine.connect() as conn:
        seqs = list(conn.scalars(text("SELECT seq FROM decision_log ORDER BY seq")))
    assert seqs == list(range(1, len(DEMO_TENANTS) + 1))
    permits = reviewer_of(PERMITS)
    verified = desk_rls.get("/decision-log/verify", headers=permits).json()
    assert verified["ok"] is True and verified["records"] == len(DEMO_TENANTS)
    head = desk_rls.get("/decision-log/checkpoint", headers=permits).json()
    assert head["head_seq"] == len(DEMO_TENANTS) and set(head) == {"head_seq", "head_hash",
                                                                   "records"}  # fmt: skip


def test_platform_reads_are_widened_only_where_named(
    populated: list[dict[str, Any]], desk_rls: TestClient
) -> None:
    """A governance officer's forecast totals cover every tenant (no findings shown); a
    reviewer's cover their own tenant, with the platform-wide review rate."""
    officer = dict(headers(user("go", platform=("governance-officer",)), "review-desk"))
    totals = desk_rls.get("/forecast", headers=officer).json()
    assert {t["tenant"] for t in totals["by_tenant"]} == set(DEMO_TENANTS)
    mine = desk_rls.get("/forecast", headers=reviewer_of(PERMITS)).json()
    assert {t["tenant"] for t in mine["by_tenant"]} == {PERMITS}
    assert mine["rate"]["samples"] == totals["rate"]["samples"] == len(DEMO_TENANTS)
