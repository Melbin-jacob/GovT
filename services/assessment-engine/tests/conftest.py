"""Assessment-engine test fixtures: own PostgreSQL test database, truncated per test."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from ae_support import DEMO_TENANTS, TABLES, TEST_SYSTEMS
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from assessment_engine.access import get_systems
from assessment_engine.app import app
from assessment_engine.config import get_settings
from assessment_engine.db import get_session
from assessment_engine.migrate import downgrade, ensure_database, upgrade
from govhub_shared.auth import GOVERNANCE_OFFICER
from govhub_shared.auth.testing import KEYS, DefaultCaller, user
from govhub_shared.auth.web import install

DEFAULT_URL = "postgresql+psycopg://govhub:govhub@localhost:5432/assessment_engine_test"

install(app, "assessment-engine", KEYS.trust)
# Requests without their own Authorization act as one person holding every role in the
# fictional tenants (tests that check refusals send their own caller).
EVERYONE = user(
    "test-user", platform=(GOVERNANCE_OFFICER,), reviewer=DEMO_TENANTS,
    system_owner=DEMO_TENANTS, auditor=DEMO_TENANTS, tenant_admin=DEMO_TENANTS,
)  # fmt: skip


@pytest.fixture(scope="session")
def ae_database_url() -> str:
    url = os.environ.get("ASSESSMENT_TEST_DATABASE_URL", DEFAULT_URL)
    try:
        ensure_database(url)
    except OperationalError as exc:
        pytest.exit(f"PostgreSQL not reachable for assessment-engine tests: {exc}", returncode=1)
    downgrade(url)
    upgrade(url)
    return url


@pytest.fixture(scope="session")
def ae_engine(ae_database_url: str) -> Iterator[Engine]:
    engine = create_engine(ae_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def ae_db(ae_engine: Engine) -> Iterator[Session]:
    if TABLES:
        with ae_engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    with sessionmaker(bind=ae_engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture(autouse=True)
def evidence_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Every test gets its own evidence directory and no service key."""
    path = tmp_path / "evidence"
    monkeypatch.setenv("ASSESSMENT_EVIDENCE_DIR", str(path))
    monkeypatch.delenv("ASSESSMENT_EVIDENCE_KEY", raising=False)
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture
def engine_api(ae_engine: Engine, ae_db: Session) -> Iterator[TestClient]:
    factory = sessionmaker(bind=ae_engine, expire_on_commit=False)

    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_systems] = lambda: TEST_SYSTEMS
    with TestClient(app) as client:
        client.auth = DefaultCaller(EVERYONE, "assessment-engine")
        yield client
    app.dependency_overrides.clear()
