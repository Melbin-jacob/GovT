"""Calling another hub service: an httpx ``Auth`` that signs a fresh internal token for
that service (its audience) on every request, as this service (its own key).

Keys and the trust file come from the environment:
``GOVHUB_SIGNING_KEY_FILE`` / ``GOVHUB_SIGNING_KID_FILE`` (this service's private key and
its key ID) and ``GOVHUB_TRUST_FILE`` (everyone's public keys). Defaults point to the
development keys in ``var/keys``.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import httpx

from govhub_shared.auth.principal import Principal
from govhub_shared.auth.tokens import SigningKey, TrustStore, mint


def signing_key(issuer: str) -> SigningKey | None:
    """This service's key, or None if it is not configured (calls then carry no token
    and the receiving service refuses them)."""
    key_file = Path(os.environ.get("GOVHUB_SIGNING_KEY_FILE", f"var/keys/{issuer}.pem"))
    kid_file = Path(os.environ.get("GOVHUB_SIGNING_KID_FILE", f"var/keys/{issuer}.kid"))
    if not key_file.is_file() or not kid_file.is_file():
        return None
    return SigningKey.from_file(issuer, kid_file.read_text("utf-8").strip(), key_file)


def trust_store() -> TrustStore | None:
    path = Path(os.environ.get("GOVHUB_TRUST_FILE", "var/keys/trust.json"))
    return TrustStore.from_file(path) if path.is_file() else None


class ServiceAuth(httpx.Auth):
    """Sign each request as this service, for ``audience``. An Authorization header
    already on the request (e.g. a user's token passed through) is kept."""

    def __init__(self, key: SigningKey | None, audience: str, *, all_tenants: bool = False):
        self.key = key
        self.audience = audience
        self.all_tenants = all_tenants

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        if self.key is not None and "authorization" not in request.headers:
            who = Principal(kind="service", id=self.key.issuer, all_tenants=self.all_tenants)
            request.headers["Authorization"] = f"Bearer {mint(self.key, who, self.audience)}"
        yield request
