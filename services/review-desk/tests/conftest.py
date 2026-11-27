"""Review-desk test fixtures: own PostgreSQL test database, truncated before each test."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from review_desk_support import FIXTURES, REVIEW_TABLES
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from review_desk.app import app
from review_desk.db import get_session
from review_desk.migrate import downgrade, ensure_database, upgrade

DEFAULT_URL = "postgresql+psycopg://govhub:govhub@localhost:5432/review_desk_test"


@pytest.fixture(scope="session")
def review_database_url() -> str:
    url = os.environ.get("REVIEW_DESK_TEST_DATABASE_URL", DEFAULT_URL)
    try:
        ensure_database(url)
    except OperationalError as exc:
        pytest.exit(f"PostgreSQL not reachable for review-desk tests: {exc}", returncode=1)
    downgrade(url)
    upgrade(url)
    return url


@pytest.fixture(scope="session")
def review_engine(review_database_url: str) -> Iterator[Engine]:
    engine = create_engine(review_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def review_db(review_engine: Engine) -> Iterator[Session]:
    with review_engine.begin() as conn:
        # The log refuses TRUNCATE; as its owner, the test user may switch that off briefly.
        conn.execute(text("ALTER TABLE decision_log DISABLE TRIGGER USER"))
        conn.execute(text(f"TRUNCATE {', '.join(REVIEW_TABLES)} RESTART IDENTITY CASCADE"))
        conn.execute(text("ALTER TABLE decision_log ENABLE TRIGGER USER"))
    with sessionmaker(bind=review_engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def desk(review_engine: Engine, review_db: Session) -> Iterator[TestClient]:
    factory = sessionmaker(bind=review_engine, expire_on_commit=False)

    def _session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def impact_report() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "impact-report.json").read_text("utf-8"))
    return data
