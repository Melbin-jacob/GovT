"""Migrations are serialized by a PostgreSQL advisory lock (safe with several replicas).

Runs against a separate scratch database so the shared test schema is untouched.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
from alembic.script import ScriptDirectory
from conftest import _ensure_database
from sqlalchemy import create_engine, inspect, make_url, text

from rulebook.migrate import MIGRATION_LOCK_KEY, alembic_config, downgrade, upgrade

HEAD = ScriptDirectory.from_config(alembic_config("postgresql://unused")).get_current_head()


@pytest.fixture
def scratch_url(database_url: str) -> Iterator[str]:
    url = make_url(database_url).set(database=f"{make_url(database_url).database}_migrate")
    rendered = url.render_as_string(hide_password=False)
    _ensure_database(rendered)
    downgrade(rendered)
    yield rendered
    downgrade(rendered)


def _head(url: str) -> str | None:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            if not inspect(conn).has_table("alembic_version"):
                return None
            return conn.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()


def test_concurrent_upgrades_all_succeed(scratch_url: str) -> None:
    errors: list[BaseException] = []
    start = threading.Barrier(6)

    def run() -> None:
        try:
            start.wait()
            upgrade(scratch_url)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, daemon=True) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads), "migrations deadlocked"
    assert errors == []
    assert _head(scratch_url) == HEAD


def test_upgrade_waits_for_the_lock(scratch_url: str) -> None:
    holder = create_engine(scratch_url)
    done = threading.Event()
    try:
        with holder.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
            worker = threading.Thread(
                target=lambda: (upgrade(scratch_url), done.set()), daemon=True
            )
            worker.start()
            time.sleep(1.0)
            assert not done.is_set(), "upgrade ran while another session held the lock"
            assert _head(scratch_url) is None
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY})
            conn.commit()
            worker.join(timeout=60)
        assert done.is_set()
        assert _head(scratch_url) == HEAD
    finally:
        holder.dispose()


def test_every_table_is_truncated_between_tests() -> None:
    """A table missing from conftest.TABLES leaks rows between tests."""
    from conftest import TABLES

    from rulebook.models import Base

    assert set(Base.metadata.tables) <= set(TABLES)
