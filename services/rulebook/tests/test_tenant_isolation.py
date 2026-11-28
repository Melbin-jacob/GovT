"""Row-level security: through the app role, one tenant never reads or writes another's
systems or profile assignments, even where application code forgets to filter. Requests
run with sessions logged in as a non-owner role, as in a deployment (the other tests use
the owner, which RLS does not bind)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker
from test_impact import REQUEST, seed

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
from rulebook import inventory as inv
from rulebook.app import app
from rulebook.db import get_session
from rulebook.models import ProfileAssignment

TENANT_TABLES = ("ai_systems", "profile_assignments")
PERMITS, OTHER = "office-fictional-permits", "agency-sample-benefits"


@pytest.fixture(scope="session")
def app_engine(engine: Engine) -> Iterator[Engine]:
    e = app_role_engine(engine)
    yield e
    e.dispose()


@pytest.fixture
def client_rls(client: TestClient, app_engine: Engine) -> TestClient:
    """The rulebook API with every request's session logged in as the app role."""
    factory = sessionmaker(bind=app_engine, expire_on_commit=False)

    def _session() -> Iterator[Session]:
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    return client


@pytest.fixture
def populated(client_rls: TestClient) -> dict[str, str]:
    """Inventory (connector-hub's all-tenants sync) and one profile assignment by each
    tenant's own tenant-admin, through the app role. Returns tenant -> a system ID."""
    seed(client_rls)
    systems = client_rls.get("/inventory").json()["systems"]
    chosen = {}
    for tenant in (PERMITS, OTHER):
        system = next(s["system_id"] for s in systems if s["tenant"] == tenant)
        admin = headers(user(f"ta-{tenant}", tenant_admin=[tenant]), "rulebook")
        resp = client_rls.put(f"/systems/{system}/profiles", json={"profiles": []},
                              headers=admin)  # fmt: skip
        assert resp.status_code == 200, resp.text
        chosen[tenant] = system
    return chosen


def test_every_tenant_table_has_row_level_security(engine: Engine) -> None:
    with engine.connect() as conn:
        with_tenant = set(conn.scalars(text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'tenant'")))  # fmt: skip
    assert with_tenant == set(TENANT_TABLES)
    for table in TENANT_TABLES:
        assert rls_enabled(engine, table) == (True, False), table  # enabled, not forced


def test_an_unbound_connection_sees_nothing(
    populated: dict[str, str], engine: Engine, app_engine: Engine
) -> None:
    for table in TENANT_TABLES:
        assert {PERMITS, OTHER} <= set(owner_tenants(engine, table)), table
        with unbound_session(app_engine) as s:
            assert s.scalar(text(f"SELECT count(*) FROM {table}")) == 0, table  # noqa: S608
        assert tenants_seen(app_engine, table, tenancy.NO_TENANTS) == {}, table


def test_a_bound_connection_sees_only_its_tenants(
    populated: dict[str, str], engine: Engine, app_engine: Engine
) -> None:
    for table in TENANT_TABLES:
        owner = owner_tenants(engine, table)
        assert tenants_seen(app_engine, table, frozenset({PERMITS})) == {PERMITS: owner[PERMITS]}
        assert tenants_seen(app_engine, table, tenancy.ALL_TENANTS) == owner, table


def test_code_that_forgets_the_tenant_still_finds_nothing(
    populated: dict[str, str], app_engine: Engine
) -> None:
    """The inventory functions, called without any access check: only the bound
    tenant's systems and assignments."""
    with session(app_engine, frozenset({PERMITS})) as s:
        _, systems = inv.current_inventory(s)
        assert {x.tenant for x in systems} == {PERMITS}
        assert s.get(ProfileAssignment, populated[OTHER]) is None
        mine = inv.assignments_hash(s)
    with session(app_engine, tenancy.ALL_TENANTS) as s:
        assert inv.assignments_hash(s) != mine  # another tenant's choices are not mixed in


def test_writes_into_another_tenant_are_refused(
    populated: dict[str, str], app_engine: Engine
) -> None:
    scope = frozenset({PERMITS})
    with session(app_engine, scope) as s, pytest.raises(ProgrammingError, match="row-level"):
        s.add(ProfileAssignment(system_id="SYS-PLANTED", tenant=OTHER, profiles=[], set_by="x"))
        s.flush()
    with session(app_engine, scope) as s, pytest.raises(ProgrammingError, match="row-level"):
        s.execute(text("UPDATE profile_assignments SET tenant = :o WHERE tenant = :p"),
                  {"o": OTHER, "p": PERMITS})  # fmt: skip
    with session(app_engine, scope) as s:
        gone = s.execute(text("DELETE FROM profile_assignments WHERE tenant = :o"), {"o": OTHER})
        assert gone.rowcount == 0  # type: ignore[attr-defined]
        s.rollback()


def test_the_api_through_the_app_role_keeps_tenants_apart(
    populated: dict[str, str], client_rls: TestClient
) -> None:
    permits = headers(user("rv", reviewer=[PERMITS]), "rulebook")
    systems = client_rls.get("/inventory", headers=permits).json()["systems"]
    assert {s["tenant"] for s in systems} == {PERMITS}
    assert client_rls.get(f"/systems/{populated[OTHER]}", headers=permits).status_code == 404
    report = client_rls.post("/impact-reports", json=REQUEST, headers=permits).json()
    listed = report["systems"] + report["excluded_systems"]
    assert listed and {s["system_id"] for s in listed} <= {s["system_id"] for s in systems}
