"""OIDC sign-in (authorization code flow with PKCE) against the configured provider.

control-centre is the only component that talks to the sign-in provider, and only to the
hosts in ``OIDC_ALLOWED_HOSTS`` (HTTPS; plain HTTP only with ``OIDC_ALLOW_INSECURE_HTTP=1``
for a local Keycloak). No redirects are followed. The ID token is verified against the
provider's published keys: signature, issuer, audience (the client ID), expiry, nonce.
The provider's discovery may be fetched from an internal address (``OIDC_DISCOVERY_URL``,
e.g. http://keycloak:8080 inside Compose) while the browser uses the public one.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from sqlalchemy.orm import Session

from control_centre.identity.rolemap import RoleMap
from control_centre.identity.sessions import now
from control_centre.models import OidcLogin
from govhub_shared.auth import Principal

LOGIN_TTL = timedelta(minutes=10)
ID_TOKEN_ALGORITHMS = ["RS256", "ES256", "PS256"]


class OidcError(RuntimeError):
    pass


@dataclass
class OidcConfig:
    issuer: str
    client_id: str
    client_secret: str
    redirect_url: str
    allowed_hosts: frozenset[str]
    discovery_url: str = ""
    allow_insecure_http: bool = False
    scopes: str = "openid profile email"

    def check(self) -> list[str]:
        problems = []
        for name in ("issuer", "client_id", "client_secret", "redirect_url"):
            if not getattr(self, name):
                problems.append(f"OIDC_{name.upper()} is not set")
        for url in (self.issuer, self.discovery_url):
            if url:
                problems += self.url_problems(url)
        return problems

    def url_problems(self, url: str) -> list[str]:
        parts = urlsplit(url)
        problems = []
        if parts.hostname not in self.allowed_hosts:
            problems.append(f"{parts.hostname} is not in OIDC_ALLOWED_HOSTS")
        if parts.scheme != "https" and not (parts.scheme == "http" and self.allow_insecure_http):
            problems.append(f"{url}: HTTPS required (OIDC_ALLOW_INSECURE_HTTP=1 for local only)")
        return problems


class OidcClient:
    def __init__(self, config: OidcConfig, http: httpx.Client | None = None) -> None:
        self.config = config
        self.http = http or httpx.Client(timeout=15.0, follow_redirects=False)
        self._discovery: dict[str, Any] | None = None

    def _get(self, url: str) -> dict[str, Any]:
        if problems := self.config.url_problems(url):
            raise OidcError("; ".join(problems))
        response = self.http.get(url)
        if response.status_code != 200:
            raise OidcError(f"{urlsplit(url).hostname}: HTTP {response.status_code}")
        data: dict[str, Any] = response.json()
        return data

    def discovery(self) -> dict[str, Any]:
        if self._discovery is None:
            base = (self.config.discovery_url or self.config.issuer).rstrip("/")
            data = self._get(f"{base}/.well-known/openid-configuration")
            if data.get("issuer") != self.config.issuer:
                raise OidcError("the provider's issuer does not match OIDC_ISSUER")
            self._discovery = data
        return self._discovery

    def begin(self, session: Session, next_path: str) -> str:
        """Record a login in progress; return the provider's authorization URL."""
        state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        session.add(OidcLogin(state=state, nonce=nonce, verifier=verifier,
                              next_path=next_path, created_at=now()))  # fmt: skip
        session.commit()
        query = urlencode({
            "response_type": "code", "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_url, "scope": self.config.scopes,
            "state": state, "nonce": nonce,
            "code_challenge": challenge.rstrip(b"=").decode(), "code_challenge_method": "S256",
        })  # fmt: skip
        return f"{self.discovery()['authorization_endpoint']}?{query}"

    def finish(
        self, session: Session, state: str, code: str, role_map: RoleMap
    ) -> tuple[Principal, str]:
        """Exchange the code (once), verify the ID token, map claims to roles."""
        login = session.get(OidcLogin, state)
        if login is None:
            raise OidcError("unknown or already used sign-in")
        session.delete(login)
        session.commit()
        if now() - login.created_at > LOGIN_TTL:
            raise OidcError("the sign-in took too long; start again")
        endpoint = self.discovery()["token_endpoint"]
        if problems := self.config.url_problems(endpoint):
            raise OidcError("; ".join(problems))
        response = self.http.post(endpoint, data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": self.config.redirect_url, "code_verifier": login.verifier,
            "client_id": self.config.client_id, "client_secret": self.config.client_secret,
        })  # fmt: skip
        if response.status_code != 200:
            raise OidcError(f"token endpoint: HTTP {response.status_code}")
        id_token = response.json().get("id_token")
        if not id_token:
            raise OidcError("no ID token in the provider's answer")
        claims = self.verify_id_token(str(id_token))
        if claims.get("nonce") != login.nonce:
            raise OidcError("nonce mismatch")
        return role_map.principal(claims), login.next_path

    def verify_id_token(self, token: str) -> dict[str, Any]:
        jwks = self._get(self.discovery()["jwks_uri"])
        kid = jwt.get_unverified_header(token).get("kid")
        keys = [k for k in jwks.get("keys", []) if k.get("kid") == kid]
        if not keys:
            raise OidcError("the ID token's key is not published by the provider")
        key = jwt.PyJWK.from_json(json.dumps(keys[0]))
        try:
            claims: dict[str, Any] = jwt.decode(
                token, key.key, algorithms=ID_TOKEN_ALGORITHMS, audience=self.config.client_id,
                issuer=self.config.issuer, leeway=30,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )  # fmt: skip
        except jwt.PyJWTError as exc:
            raise OidcError(f"ID token refused: {exc.__class__.__name__}") from exc
        return claims

    def end_session_url(self, post_logout: str) -> str | None:
        endpoint = self.discovery().get("end_session_endpoint")
        if not endpoint:
            return None
        query = urlencode({"client_id": self.config.client_id,
                           "post_logout_redirect_uri": post_logout})  # fmt: skip
        return f"{endpoint}?{query}"
