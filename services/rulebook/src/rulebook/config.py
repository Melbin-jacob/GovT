"""Runtime configuration, read from environment variables (prefix ``RULEBOOK_``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RULEBOOK_")

    database_url: str = "postgresql+psycopg://govhub:govhub@localhost:5432/rulebook"


@lru_cache
def get_settings() -> Settings:
    return Settings()
