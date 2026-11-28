"""Runtime configuration (environment variables, prefix ``ASSESSMENT_``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASSESSMENT_", populate_by_name=True)

    database_url: str = "postgresql+psycopg://govhub:govhub@localhost:5432/assessment_engine"
    # Migrations run as the database owner; the service runs as the app role (no
    # ownership, no row-level-security bypass). Empty: the runtime URL does both.
    migration_database_url: str = ""
    # Evidence files live on their own volume (never in git, never in an image). Encrypt the
    # volume at rest where the platform allows (encrypted StorageClass / disk encryption).
    # With ASSESSMENT_EVIDENCE_KEY set (base64, 32 bytes) files are also encrypted by the
    # service itself (AES-256-GCM).
    evidence_dir: str = "var/evidence"
    evidence_key: str = Field(default="", repr=False)
    max_upload_bytes: int = 20 * 1024 * 1024
    # PLACEHOLDER: retention is owned by control-centre later (TODO(control-centre)).
    # None = keep; nothing is deleted automatically yet.
    evidence_retention_days: int | None = None
    # Internal hub services.
    rulebook_url: str = Field(default="http://127.0.0.1:8000", validation_alias="RULEBOOK_URL")
    review_desk_url: str = Field(
        default="http://127.0.0.1:8002", validation_alias="REVIEW_DESK_URL"
    )
    assessment_config_path: str = "data/config/assessment.toml"
    rules_dir: str = "data/rules"


@lru_cache
def get_settings() -> Settings:
    return Settings()
