"""Control-centre tests: pages with fake hub services; control-centre's own database
(tenants) in ``CONTROL_CENTRE_TEST_DATABASE_URL`` for the tests that ask for it."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from cc_support import FakeHub
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from control_centre.app import app
from control_centre.db import get_session
from control_centre.migrate import downgrade, ensure_database, upgrade
from control_centre.web import get_backends
from govhub_shared.auth.testing import KEYS
from govhub_shared.auth.web import install

DEFAULT_URL = "postgresql+psycopg://govhub:govhub@localhost:5432/control_centre_test"
TABLES = ("tenants",)

install(app, "control-centre", KEYS.trust)


@pytest.fixture(scope="session")
def cc_engine() -> Iterator[Engine]:
    url = os.environ.get("CONTROL_CENTRE_TEST_DATABASE_URL", DEFAULT_URL)
    try:
        ensure_database(url)
    except OperationalError as exc:
        pytest.exit(f"PostgreSQL not reachable for control-centre tests: {exc}", returncode=1)
    downgrade(url)
    upgrade(url)
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def cc_db(cc_engine: Engine) -> Iterator[Session]:
    with cc_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
    factory = sessionmaker(bind=cc_engine, expire_on_commit=False)

    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    with factory() as session:
        yield session
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def hub() -> FakeHub:
    return FakeHub()


@pytest.fixture
def ui(hub: FakeHub) -> Iterator[TestClient]:
    app.dependency_overrides[get_backends] = hub.backends
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_backends, None)
