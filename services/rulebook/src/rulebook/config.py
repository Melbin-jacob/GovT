"""Runtime configuration, read from environment variables (prefix ``RULEBOOK_``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RULEBOOK_")

    database_url: str = "postgresql+psycopg://govhub:govhub@localhost:5432/rulebook"
    # Relative paths resolve against the working directory (/app in the container).
    due_dates_path: str = "data/config/due-dates.toml"
    # Approval-log checkpoints outside the database (empty disables).
    approval_checkpoint_file: str = "var/checkpoints/approval-log.jsonl"


@lru_cache
def get_settings() -> Settings:
    return Settings()
