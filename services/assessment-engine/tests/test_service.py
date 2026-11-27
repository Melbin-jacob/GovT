"""Service basics: health, readiness, migrations, evidence policy."""

from __future__ import annotations

from ae_support import TABLES
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect

from assessment_engine.migrate import alembic_config
from assessment_engine.models import Base


def test_health_and_ready(engine_api: TestClient) -> None:
    assert engine_api.get("/health").json() == {"status": "ok"}
    assert engine_api.get("/ready").json() == {"status": "ready"}


def test_migrations_reach_head(ae_engine: Engine) -> None:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    with ae_engine.connect() as conn:
        version = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
    assert version == head


def test_every_table_is_truncated_between_tests(ae_engine: Engine) -> None:
    assert set(TABLES) == set(Base.metadata.tables)
    assert set(Base.metadata.tables) <= set(inspect(ae_engine).get_table_names())


def test_evidence_policy_has_a_retention_placeholder(engine_api: TestClient) -> None:
    policy = engine_api.get("/evidence-policy").json()
    assert policy["retention_status"].startswith("PLACEHOLDER")
    assert policy["passage_text_logged"] is False
    assert policy["service_encryption"] == "off"
