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
    assessment_engine_url: str = Field(
        default="http://127.0.0.1:8005", validation_alias="ASSESSMENT_ENGINE_URL"
    )
    database_url: str = "postgresql+psycopg://govhub:govhub@localhost:5432/control_centre"
    # Public keys of every token issuer (govhub-trust/1); see govhub_shared.auth.devkeys.
    trust_file: str = Field(default="var/keys/trust.json", validation_alias="GOVHUB_TRUST_FILE")
    # Sign-in: "oidc" (production) or "demo" (labelled, fictional users; refuses to start
    # unless bound internally and every tenant is synthetic).
    auth_mode: str = Field(default="oidc", validation_alias="AUTH_MODE")
    internal_only: bool = Field(default=False, validation_alias="GOVHUB_INTERNAL_ONLY")
    demo_users_file: str = "data/demo/users.toml"
    role_map_file: str = "data/config/oidc-roles.toml"
    # The key control-centre signs users' internal tokens with (and its ID, for rotation).
    signing_key_file: str = Field(
        default="var/keys/control-centre.pem", validation_alias="GOVHUB_SIGNING_KEY_FILE"
    )
    signing_kid_file: str = Field(
        default="var/keys/control-centre.kid", validation_alias="GOVHUB_SIGNING_KID_FILE"
    )
    # OIDC (AUTH_MODE=oidc). The client secret comes from the environment or a secret file.
    oidc_issuer: str = Field(default="", validation_alias="OIDC_ISSUER")
    oidc_discovery_url: str = Field(default="", validation_alias="OIDC_DISCOVERY_URL")
    oidc_client_id: str = Field(default="", validation_alias="OIDC_CLIENT_ID")
    oidc_client_secret: str = Field(default="", validation_alias="OIDC_CLIENT_SECRET", repr=False)
    oidc_redirect_url: str = Field(default="", validation_alias="OIDC_REDIRECT_URL")
    oidc_allowed_hosts: str = Field(default="", validation_alias="OIDC_ALLOWED_HOSTS")
    oidc_allow_insecure_http: bool = Field(
        default=False, validation_alias="OIDC_ALLOW_INSECURE_HTTP"
    )
    # Cookies are Secure unless explicitly local (plain-HTTP demo or local Keycloak).
    secure_cookies: bool = Field(default=True, validation_alias="GOVHUB_SECURE_COOKIES")
    # Labels. A deployment showing only the synthetic demo directive and the fictional
    # inventory keeps both on; erring this way never presents test data as real.
    synthetic_data: bool = True
    fictional_inventory: bool = True
    # Demo defaults for the forms (reports never read the clock: as_of is an input).
    default_instrument: str = "example-widgets"
    default_catalog: str = "example-widgets"
    default_as_of: str = "2026-12-01"


@lru_cache
def get_settings() -> Settings:
    return Settings()
