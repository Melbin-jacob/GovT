"""Run Alembic migrations programmatically (no alembic.ini needed at runtime).

Safe with several replicas starting at once: every run takes a PostgreSQL
transaction-level advisory lock first, and runs the migrations on that same connection
and transaction. Other replicas block on the lock; when the first commits, they acquire
it, find the schema already at ``head`` and do nothing. The lock is released
automatically at commit or rollback, including if the process dies.
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from rulebook.config import get_settings

# Any fixed 64-bit key, unique to this application ("RULEBOOK" in ASCII).
MIGRATION_LOCK_KEY = 0x52554C45424F4F4B


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "rulebook:migrations")
    cfg.set_main_option(
        "sqlalchemy.url",
        database_url or (get_settings().migration_database_url or get_settings().database_url),
    )
    return cfg


def _run_locked(database_url: str | None, direction: str, revision: str) -> None:
    cfg = alembic_config(database_url)
    engine = create_engine(cfg.get_main_option("sqlalchemy.url") or "")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
            )
            cfg.attributes["connection"] = connection
            if direction == "upgrade":
                command.upgrade(cfg, revision)
            else:
                command.downgrade(cfg, revision)
    finally:
        engine.dispose()


def upgrade(database_url: str | None = None, revision: str = "head") -> None:
    _run_locked(database_url, "upgrade", revision)


def downgrade(database_url: str | None = None, revision: str = "base") -> None:
    _run_locked(database_url, "downgrade", revision)
