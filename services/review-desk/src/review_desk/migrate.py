"""Migrations under a PostgreSQL advisory lock (safe with several replicas), and creation
of the database itself when it does not exist yet (e.g. an older local Compose volume)."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text

from review_desk.config import get_settings

MIGRATION_LOCK_KEY = 0x5245564945574453  # "REVIEWDS"


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "review_desk:migrations")
    cfg.set_main_option("sqlalchemy.url", database_url or get_settings().database_url)
    return cfg


def ensure_database(database_url: str) -> None:
    url = make_url(database_url)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
            )
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


def _run_locked(database_url: str | None, direction: str, revision: str) -> None:
    cfg = alembic_config(database_url)
    url = cfg.get_main_option("sqlalchemy.url") or ""
    ensure_database(url)
    engine = create_engine(url)
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
