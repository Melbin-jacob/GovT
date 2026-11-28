"""Fixtures for tests that need PostgreSQL.

The test database URL comes from ``RULEBOOK_TEST_DATABASE_URL`` (CI sets it); the default
is the Compose database on localhost. The database is created if missing, migrated with
Alembic once per session, and truncated before each test.
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from drafts_support import DEMO_TENANTS
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from govhub_shared.auth import GOVERNANCE_OFFICER
from govhub_shared.auth.testing import KEYS, service, token, user
from govhub_shared.auth.web import install
from rulebook.app import app
from rulebook.db import get_session
from rulebook.migrate import downgrade, upgrade

install(app, "rulebook", KEYS.trust)

REPO = Path(__file__).resolve().parents[3]
CATALOGS = REPO / "data" / "catalogs"
TABLES = (
    "catalogs",
    "catalog_versions",
    "catalog_controls",
    "source_versions",
    "profiles",
    "inventory_snapshots",
    "ai_systems",
    "draft_views",
    "draft_sessions",
    "draft_items",
    "draft_batches",
    "approval_log",
    "profile_assignments",
)
DEFAULT_URL = "postgresql+psycopg://govhub:govhub@localhost:5432/rulebook_test"


def _ensure_database(url: str) -> None:
    parsed = make_url(url)
    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": parsed.database}
            )
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    except OperationalError as exc:
        pytest.exit(
            f"PostgreSQL is not reachable at {parsed.render_as_string(hide_password=True)}. "
            "Run `docker compose up -d --wait postgres` or set RULEBOOK_TEST_DATABASE_URL.\n"
            f"{exc}",
            returncode=1,
        )
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("RULEBOOK_TEST_DATABASE_URL", DEFAULT_URL)
    _ensure_database(url)
    downgrade(url)  # start from an empty schema, exercising the downgrade path too
    upgrade(url)
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    eng = create_engine(database_url)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with engine.begin() as conn:
        # The approval log refuses TRUNCATE; as its owner, tests may switch that off briefly.
        for table in ("approval_log", "draft_views"):  # append-only outside tests
            conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
        for table in ("approval_log", "draft_views"):
            conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def client(engine: Engine, db: Session) -> Iterator[TestClient]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as test_client:
        test_client.auth = TestCaller()
        yield test_client
    app.dependency_overrides.clear()


# Tests act as one user holding every role in the demo tenants (and governance officer),
# except where a test sends its own Authorization header; the inventory snapshot is loaded
# as connector-hub's sync job (the only caller allowed to replace it).
EVERYONE = user(
    "test-user", platform=(GOVERNANCE_OFFICER,), reviewer=DEMO_TENANTS,
    tenant_admin=DEMO_TENANTS, auditor=DEMO_TENANTS, system_owner=DEMO_TENANTS,
)  # fmt: skip
SYNC_JOB = service("connector-hub", all_tenants=True)


class TestCaller(httpx.Auth):
    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        if "authorization" not in request.headers:
            who = (
                SYNC_JOB
                if (request.method, request.url.path) == ("PUT", "/inventory")
                else EVERYONE
            )
            request.headers["Authorization"] = f"Bearer {token(who, 'rulebook')}"
        yield request


def _load(lang: str) -> dict[str, Any]:
    """The committed golden catalog, pinned to version 1.0.0 so API tests can build
    later versions (1.0.1, 1.1.0 ...) on top of it whatever the committed version is."""
    from helpers import new_version

    data: dict[str, Any] = json.loads((CATALOGS / f"dadm-section6.{lang}.json").read_text())
    return new_version(data, "1.0.0")


@pytest.fixture
def golden_en() -> dict[str, Any]:
    return copy.deepcopy(_load("en"))


@pytest.fixture
def golden_fr() -> dict[str, Any]:
    return copy.deepcopy(_load("fr"))
