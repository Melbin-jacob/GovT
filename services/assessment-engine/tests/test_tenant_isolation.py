"""Row-level security: through the app role, one tenant never reads or writes another's
evidence (documents, passages, search), facts or assessments, even where application
code forgets to filter. Requests run with sessions logged in as a non-owner role, as in a
deployment (the other tests use the owner, which RLS does not bind)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from ae_support import TEST_SYSTEMS
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from assessment_engine import evidence
from assessment_engine.app import app
from assessment_engine.config import get_settings
from assessment_engine.db import get_session
from govhub_shared import tenancy
from govhub_shared.auth.testing import headers, service, user
from govhub_shared.rls_testing import (
    app_role_engine,
    owner_tenants,
    rls_enabled,
    session,
    tenants_seen,
    unbound_session,
)

TENANT_TABLES = ("evidence_documents", "evidence_passages", "system_facts", "assessments",
                 "assessment_results_documents")  # fmt: skip
SYSTEMS = {"office-fictional-permits": "SYS-002", "agency-sample-benefits": "SYS-001"}
PERMITS, OTHER = "office-fictional-permits", "agency-sample-benefits"
FACTS = {"facts": {"widgets_in_service": {"value": 2, "source": "register"}}}


@pytest.fixture(scope="session")
def app_engine(ae_engine: Engine) -> Iterator[Engine]:
    engine = app_role_engine(ae_engine)
    yield engine
    engine.dispose()


@pytest.fixture
def api_rls(engine_api: TestClient, app_engine: Engine) -> TestClient:
    """The engine API with every request's session logged in as the app role."""
    factory = sessionmaker(bind=app_engine, expire_on_commit=False)

    def _session() -> Iterator[Session]:
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    return engine_api


@pytest.fixture
def populated(api_rls: TestClient) -> dict[str, str]:
    """Evidence, facts and an assessment for one system in each of two tenants, written
    through the app role. Returns tenant -> evidence document ID."""
    docs = {}
    for tenant, system in SYSTEMS.items():
        assert TEST_SYSTEMS.tenant_of(system) == tenant
        up = api_rls.post(f"/systems/{system}/evidence",
                          files={"file": ("e.txt", f"Notices are sent for {system}.".encode())})  # fmt: skip
        assert up.status_code == 201, up.text
        docs[tenant] = up.json()["id"]
        assert api_rls.put(f"/systems/{system}/facts", json=FACTS).status_code == 200
        body = {"system_id": system, "catalog": "example-widgets", "catalog_version": "1.0.0",
                "control_ids": ["WID-6.1.2"], "as_of": "2026-12-01"}  # fmt: skip
        assert api_rls.post("/assessments", json=body).status_code == 201
    return docs


def test_every_tenant_table_has_row_level_security(ae_engine: Engine) -> None:
    with ae_engine.connect() as conn:
        with_tenant = set(conn.scalars(text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'tenant'")))  # fmt: skip
    assert with_tenant == set(TENANT_TABLES)
    for table in TENANT_TABLES:
        assert rls_enabled(ae_engine, table) == (True, False), table  # enabled, not forced


def test_an_unbound_connection_sees_nothing(
    populated: dict[str, str], ae_engine: Engine, app_engine: Engine
) -> None:
    for table in TENANT_TABLES:
        assert set(owner_tenants(ae_engine, table)) == {PERMITS, OTHER}, table
        with unbound_session(app_engine) as s:
            assert s.scalar(text(f"SELECT count(*) FROM {table}")) == 0, table  # noqa: S608
        assert tenants_seen(app_engine, table, tenancy.NO_TENANTS) == {}, table


def test_a_bound_connection_sees_only_its_tenants(
    populated: dict[str, str], ae_engine: Engine, app_engine: Engine
) -> None:
    for table in TENANT_TABLES:
        owner = owner_tenants(ae_engine, table)
        assert tenants_seen(app_engine, table, frozenset({PERMITS})) == {PERMITS: owner[PERMITS]}
        assert tenants_seen(app_engine, table, tenancy.ALL_TENANTS) == owner, table


def test_code_that_forgets_the_tenant_still_finds_nothing(
    populated: dict[str, str], app_engine: Engine
) -> None:
    """The engine's own functions, called without any access check, for another tenant's
    system or document: search, passages and facts come back empty."""
    with session(app_engine, frozenset({PERMITS})) as s:
        assert evidence.retrieve(s, SYSTEMS[OTHER], "notices sent") == []
        assert evidence.passages_of(s, populated[OTHER]) == []
        assert evidence.retrieve(s, SYSTEMS[PERMITS], "notices sent") != []
        facts = s.scalar(text("SELECT count(*) FROM system_facts WHERE system_id = :s"),
                         {"s": SYSTEMS[OTHER]})  # fmt: skip
        assert facts == 0


def test_writes_into_another_tenant_are_refused(
    populated: dict[str, str], app_engine: Engine
) -> None:
    store = evidence.store_for(get_settings())
    with session(app_engine, frozenset({PERMITS})) as s, pytest.raises(ProgrammingError,
                                                                     match="row-level"):  # fmt: skip
        evidence.ingest(s, store, system_id=SYSTEMS[OTHER], filename="x.txt",
                        data=b"Planted text.", uploaded_by="rv", tenant=OTHER)  # fmt: skip
    with session(app_engine, frozenset({PERMITS})) as s, pytest.raises(ProgrammingError,
                                                                     match="row-level"):  # fmt: skip
        s.execute(text("UPDATE system_facts SET tenant = :o WHERE tenant = :p"),
                  {"o": OTHER, "p": PERMITS})  # fmt: skip
    with session(app_engine, frozenset({PERMITS})) as s:
        gone = s.execute(text("DELETE FROM system_facts WHERE tenant = :o"), {"o": OTHER})
        assert gone.rowcount == 0  # type: ignore[attr-defined]
        s.rollback()


def test_the_api_through_the_app_role_keeps_tenants_apart(
    populated: dict[str, str], api_rls: TestClient
) -> None:
    permits = headers(user("rv", reviewer=[PERMITS]), "assessment-engine")
    mine = api_rls.get(f"/systems/{SYSTEMS[PERMITS]}/evidence", headers=permits)
    assert [d["id"] for d in mine.json()] == [populated[PERMITS]]
    search = api_rls.get(f"/systems/{SYSTEMS[PERMITS]}/evidence/search",
                         params={"q": "notices"}, headers=permits).json()  # fmt: skip
    assert search and all(SYSTEMS[OTHER] not in str(hit) for hit in search)
    for path in (f"/systems/{SYSTEMS[OTHER]}/evidence", f"/evidence/{populated[OTHER]}/passages",
                 f"/systems/{SYSTEMS[OTHER]}/facts"):  # fmt: skip
        assert api_rls.get(path, headers=permits).status_code == 404, path
    # review-desk's provenance check (all-tenants scope) still sees every tenant.
    desk = headers(service("review-desk", all_tenants=True), "assessment-engine")
    record: dict[str, Any] = api_rls.get(f"/systems/{SYSTEMS[OTHER]}/provenance",
                                         headers=desk).json()  # fmt: skip
    assert record["evidence_uploaders"] == ["test-user"]
