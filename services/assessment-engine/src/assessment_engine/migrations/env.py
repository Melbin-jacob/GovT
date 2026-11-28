"""Alembic environment for the assessment engine."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from assessment_engine.config import get_settings
from assessment_engine.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or (
        get_settings().migration_database_url or get_settings().database_url
    )


def run() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()
