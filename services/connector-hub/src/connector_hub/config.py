"""Connector-hub settings (environment). ServiceNow credentials: servicenow/config.py."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(populate_by_name=True)

    # Internal URL of the rulebook (inventory snapshots are pushed there).
    rulebook_url: str = Field(default="http://localhost:8000", validation_alias="RULEBOOK_URL")
    mapping_path: str = Field(
        default="data/config/servicenow-mapping.toml", validation_alias="SERVICENOW_MAPPING_PATH"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
