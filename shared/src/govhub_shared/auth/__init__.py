"""Hub identity: short-lived internal tokens, roles per tenant, and the request check.

Users sign in at control-centre (OIDC); control-centre then issues **internal tokens**
(ES256, with a key ID so keys rotate) for one target service at a time, valid 5 minutes.
Services also call each other with tokens signed by their own keys. A service verifies
every token against a local trust file (public keys only): no service contacts the
sign-in provider, so only connector-hub and control-centre ever call out.
"""

from govhub_shared.auth.principal import (
    AUDITOR,
    GOVERNANCE_OFFICER,
    PLATFORM_ADMIN,
    PLATFORM_ROLES,
    PROFILE_ASSIGNMENT,
    REVIEWER,
    ROLES,
    SYSTEM_OWNER,
    TENANT_ADMIN,
    TENANT_ROLES,
    Principal,
)
from govhub_shared.auth.tokens import (
    ALGORITHM,
    DEFAULT_TTL,
    LEEWAY,
    SigningKey,
    TokenError,
    TrustStore,
    generate_key,
    mint,
    verify,
)

__all__ = [
    "ALGORITHM",
    "AUDITOR",
    "DEFAULT_TTL",
    "GOVERNANCE_OFFICER",
    "LEEWAY",
    "PLATFORM_ADMIN",
    "PLATFORM_ROLES",
    "PROFILE_ASSIGNMENT",
    "REVIEWER",
    "ROLES",
    "SYSTEM_OWNER",
    "TENANT_ADMIN",
    "TENANT_ROLES",
    "Principal",
    "SigningKey",
    "TokenError",
    "TrustStore",
    "generate_key",
    "mint",
    "verify",
]
