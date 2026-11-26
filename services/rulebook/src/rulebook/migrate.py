"""Run Alembic migrations programmatically (no alembic.ini needed at runtime)."""

from __future__ import annotations

from alembic import command
from alembic.config import Config

from rulebook.config import get_settings


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "rulebook:migrations")
    cfg.set_main_option("sqlalchemy.url", database_url or get_settings().database_url)
    return cfg


def upgrade(database_url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade(database_url: str | None = None, revision: str = "base") -> None:
    command.downgrade(alembic_config(database_url), revision)
