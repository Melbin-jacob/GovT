"""Assessment-engine test fixtures: own PostgreSQL test database, truncated per test."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from ae_support import TABLES
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from assessment_engine.app import app
from assessment_engine.config import get_settings
from assessment_engine.db import get_session
from assessment_engine.migrate import downgrade, ensure_database, upgrade

DEFAULT_URL = "postgresql+psycopg://govhub:govhub@localhost:5432/assessment_engine_test"


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
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
