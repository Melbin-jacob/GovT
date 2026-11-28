"""Runtime configuration (environment variables, prefix ``REVIEW_DESK_``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REVIEW_DESK_", populate_by_name=True)

    database_url: str = "postgresql+psycopg://govhub:govhub@localhost:5432/review_desk"
    # Internal URL of connector-hub (tasks in ServiceNow). Empty: side effects are recorded
    # as "not sent" in the decision log instead.
    connector_hub_url: str = Field(default="", validation_alias="CONNECTOR_HUB_URL")
    # The assessment engine (evidence and facts provenance for the conflict-of-interest
    # check). Empty: no provenance (tests, review-only deployments).
    assessment_engine_url: str = Field(default="", validation_alias="ASSESSMENT_ENGINE_URL")
    # Relative paths resolve against the working directory (/app in the container).
    review_rate_path: str = "data/config/review-rate.toml"
    # Decision-log checkpoints outside the database (checkpoints.py). Every N decisions;
    # 0 disables. The file must live on a volume separate from the database's.
    checkpoint_every: int = 1
    checkpoint_file: str = "var/checkpoints/decision-log.jsonl"


@lru_cache
def get_settings() -> Settings:
    return Settings()
