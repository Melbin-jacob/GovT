"""Runtime configuration (environment variables, prefix ``CONTROL_CENTRE_``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONTROL_CENTRE_", populate_by_name=True)

    # Internal service URLs (calls between hub services stay inside the deployment).
    rulebook_url: str = Field(default="http://127.0.0.1:8000", validation_alias="RULEBOOK_URL")
    review_desk_url: str = Field(
        default="http://127.0.0.1:8002", validation_alias="REVIEW_DESK_URL"
    )
    connector_hub_url: str = Field(
        default="http://127.0.0.1:8001", validation_alias="CONNECTOR_HUB_URL"
    )
    # Placeholder identity sent to review-desk. TODO(control-centre): OIDC sign-in.
    demo_user: str = "demo-reviewer-01"
    demo_role: str = "reviewer"
    # Labels. A deployment showing only the synthetic demo directive and the fictional
    # inventory keeps both on; erring this way never presents test data as real.
    synthetic_data: bool = True
    fictional_inventory: bool = True
    # Demo defaults for the forms (reports never read the clock: as_of is an input).
    default_instrument: str = "example-widgets"
    default_catalog: str = "example-widgets"
    default_as_of: str = "2026-12-01"
    # Language the impact report (and so its task IDs, ServiceNow tasks and findings) is
    # produced in. The UI around it follows the page language.
    report_lang: str = "en"


@lru_cache
def get_settings() -> Settings:
    return Settings()
