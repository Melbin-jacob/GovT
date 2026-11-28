"""Control-centre tests: pages with fake hub services; control-centre's own database
(tenants) in ``CONTROL_CENTRE_TEST_DATABASE_URL`` for the tests that ask for it."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from cc_support import FakeHub, sign_in
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from control_centre.app import app
from control_centre.backends import Backends
from control_centre.config import get_settings
from control_centre.db import get_session
from control_centre.migrate import downgrade, ensure_database, upgrade
from control_centre.web import PrincipalDep, get_backends, signing_key
from govhub_shared.auth.testing import KEYS
from govhub_shared.auth.web import install

DEFAULT_URL = "postgresql+psycopg://govhub:govhub@localhost:5432/control_centre_test"
TABLES = ("tenants", "web_sessions", "oidc_logins")

install(app, "control-centre", KEYS.trust)
DEFAULT_USER = "demo-reviewer-01"


@pytest.fixture(scope="session", autouse=True)
def demo_settings(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Page tests run in demo mode with the test key for control-centre's tokens."""
    folder = tmp_path_factory.mktemp("keys")
    key = KEYS.keys["control-centre"]
    (folder / "cc.pem").write_bytes(key.private_pem)
    (folder / "cc.kid").write_text(key.kid, "utf-8")
    root = Path(__file__).parents[3]
    env = {
        "AUTH_MODE": "demo",
        "GOVHUB_SIGNING_KEY_FILE": str(folder / "cc.pem"),
        "GOVHUB_SIGNING_KID_FILE": str(folder / "cc.kid"),
        "CONTROL_CENTRE_DEMO_USERS_FILE": str(root / "data/demo/users.toml"),
        "CONTROL_CENTRE_ROLE_MAP_FILE": str(root / "data/config/oidc-roles.toml"),
        "GOVHUB_SECURE_COOKIES": "0",
    }
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    get_settings.cache_clear()
    signing_key.cache_clear()
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    get_settings.cache_clear()
    signing_key.cache_clear()


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
def ui(hub: FakeHub, cc_db: Session) -> Iterator[TestClient]:
    """Signed in (demo mode) as the fictional reviewer; ``sign_in`` switches user."""

    def backends(who: PrincipalDep) -> Backends:
        return hub.backends(who)

    app.dependency_overrides[get_backends] = backends
    with TestClient(app) as client:
        sign_in(client, DEFAULT_USER)
        yield client
    app.dependency_overrides.pop(get_backends, None)


@pytest.fixture
def anonymous(hub: FakeHub, cc_db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_backends] = lambda: hub.backends(None)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_backends, None)
