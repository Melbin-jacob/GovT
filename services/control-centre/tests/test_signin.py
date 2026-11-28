"""Sign-in: demo mode, OIDC (code flow with PKCE against a fake provider), sessions, the
internal tokens sent to the hub services, and the refusals at startup."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cc_support import FakeHub, sign_in, stub_inventory
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from control_centre.config import Settings, get_settings
from control_centre.identity import sessions
from control_centre.identity.oidc import OidcClient, OidcConfig, OidcError
from control_centre.identity.rolemap import RoleMap
from control_centre.models import Tenant, WebSession
from control_centre.screens import signin
from control_centre.startup import StartupRefusedError, check
from control_centre.tenants import seed
from govhub_shared.auth import GOVERNANCE_OFFICER, REVIEWER, verify
from govhub_shared.auth.testing import KEYS

ROOT = Path(__file__).parents[3]
ISSUER = "https://idp.example.invalid/realms/govhub"
CLIENT = "control-centre"
REDIRECT = "http://127.0.0.1:8004/auth/callback"


# --- demo mode and sessions -------------------------------------------------------------


def test_pages_need_a_signed_in_user(anonymous: TestClient) -> None:
    resp = anonymous.get("/fr/inventory?tenant=x", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/fr/sign-in?next=/fr/inventory%3Ftenant%3Dx"
    page = anonymous.get(resp.headers["location"]).text
    assert "Mode démo : choisissez un utilisateur fictif" in page
    assert "demo-officer-01 (Olivia Officer (fictional))" in page
    assert 'class="site-nav"' not in page  # no navigation before signing in


def test_demo_sign_in_and_sign_out(anonymous: TestClient, cc_db: Session) -> None:
    sign_in(anonymous, "demo-auditor-01")
    cookie = anonymous.cookies.get(sessions.COOKIE)
    assert cookie and cc_db.query(WebSession).count() == 1
    stored = cc_db.query(WebSession).one()
    assert stored.token_hash != cookie and len(stored.token_hash) == 64  # only the hash
    page = anonymous.get("/en/").text
    assert 'data-user="demo-auditor-01"' in page and "auditor" in page
    out = anonymous.post("/en/sign-out", follow_redirects=False)
    assert out.headers["location"] == "/en/sign-in"
    anonymous.cookies.set(sessions.COOKIE, cookie)  # replaying the old cookie
    assert anonymous.get("/en/", follow_redirects=False).status_code == 303


def test_sessions_expire(anonymous: TestClient, cc_db: Session) -> None:
    sign_in(anonymous, "demo-reviewer-01")
    row = cc_db.query(WebSession).one()
    row.last_seen = row.last_seen - sessions.IDLE - timedelta(seconds=1)
    cc_db.commit()
    assert anonymous.get("/en/", follow_redirects=False).status_code == 303
    sign_in(anonymous, "demo-reviewer-01")
    newest = cc_db.query(WebSession).order_by(WebSession.created_at.desc()).first()
    assert newest is not None
    newest.created_at = newest.created_at - sessions.ABSOLUTE - timedelta(seconds=1)
    cc_db.commit()
    assert anonymous.get("/en/", follow_redirects=False).status_code == 303


def test_hub_services_receive_an_internal_token_per_service(ui: TestClient, hub: FakeHub) -> None:
    stub_inventory(hub)
    ui.get("/en/inventory")
    (call,) = [r for r in hub.rulebook.requests if r.url.path == "/inventory"]
    token = call.headers["Authorization"].removeprefix("Bearer ")
    assert jwt.get_unverified_header(token)["kid"] == KEYS.keys["control-centre"].kid
    who = verify(token, KEYS.trust, "rulebook")
    assert who.id == "demo-reviewer-01" and who.has(REVIEWER, "office-fictional-permits")
    with pytest.raises(Exception, match="not for review-desk"):
        verify(token, KEYS.trust, "review-desk")


def test_demo_banner_only_in_demo_mode(ui: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert 'data-auth-mode="demo"' in ui.get("/en/").text
    monkeypatch.setenv("AUTH_MODE", "oidc")
    get_settings.cache_clear()
    try:
        page = ui.get("/en/sign-in").text
        assert 'data-auth-mode="demo"' not in page and "no sign-in" not in page
        assert ui.post("/en/sign-in/demo", data={"user": "demo-reviewer-01"}).status_code == 404
        assert 'action="/auth/login"' in page
    finally:
        monkeypatch.setenv("AUTH_MODE", "demo")
        get_settings.cache_clear()


# --- roles from claims ------------------------------------------------------------------


def test_role_map_keycloak_group_paths() -> None:
    roles = RoleMap.from_file(ROOT / "data/config/oidc-roles.toml")
    who = roles.principal({
        "preferred_username": "kc-user", "name": "Kay Fictional",
        "groups": ["/govhub/office-fictional-permits/reviewer",
                   "/govhub/office-fictional-permits/tenant-admin",
                   "/govhub/dept-example-services/auditor",
                   "/govhub/platform/governance-officer",
                   "/govhub/platform/root",            # unknown: dropped
                   "/govhub/dept-example-services/governance-officer",  # misplaced: dropped
                   "/other/thing"],
    })  # fmt: skip
    assert who.id == "kc-user" and who.name == "Kay Fictional"
    assert who.platform_roles == {GOVERNANCE_OFFICER}
    assert who.tenant_roles == {
        "office-fictional-permits": {"reviewer", "tenant-admin"},
        "dept-example-services": {"auditor"},
    }


def test_role_map_entra_group_ids() -> None:
    roles = RoleMap(user_id_claim="oid", groups={
        "11111111-aaaa": {"tenant": "office-fictional-permits", "role": "reviewer"},
        "22222222-bbbb": {"platform": "platform-admin"},
    })  # fmt: skip
    who = roles.principal({"oid": "entra-oid-1", "name": "E", "groups": ["11111111-aaaa",
                                                                          "22222222-bbbb", "x"]})  # fmt: skip
    assert who.id == "entra-oid-1"
    assert who.platform_roles == {"platform-admin"}
    assert who.tenant_roles == {"office-fictional-permits": {"reviewer"}}


# --- OIDC against a fake provider -------------------------------------------------------


class FakeProvider:
    """Discovery, JWKS and a token endpoint; checks PKCE and the client secret."""

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.codes: dict[str, dict[str, Any]] = {}
        self.audience = CLIENT
        self.nonce_override: str | None = None
        self.calls: list[str] = []

    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [{**jwk, "kid": "idp-1", "use": "sig", "alg": "RS256"}]}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
                "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
                "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
                "end_session_endpoint": f"{ISSUER}/protocol/openid-connect/logout",
            })  # fmt: skip
        if path.endswith("/certs"):
            return httpx.Response(200, json=self.jwks())
        if path.endswith("/token"):
            form = parse_qs(request.content.decode())
            code = self.codes.pop(form["code"][0], None)
            verifier = form["code_verifier"][0]
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            if (code is None or form["client_secret"] != ["cs-secret"]
                    or challenge.rstrip(b"=").decode() != code["challenge"]):  # fmt: skip
                return httpx.Response(400, json={"error": "invalid_grant"})
            now = int(time.time())
            claims = {
                "iss": ISSUER, "aud": self.audience, "sub": "kc-sub-1", "iat": now,
                "exp": now + 300, "nonce": self.nonce_override or code["nonce"],
                "preferred_username": "kc-reviewer", "name": "Kim Reviewer (fictional)",
                "groups": ["/govhub/office-fictional-permits/reviewer"],
            }  # fmt: skip
            token = jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "idp-1"})
            return httpx.Response(200, json={"id_token": token, "access_token": "x"})
        return httpx.Response(404)

    def authorize(self, url: str) -> str:
        """The browser's trip to the provider: returns the callback query."""
        query = parse_qs(urlsplit(url).query)
        assert query["code_challenge_method"] == ["S256"]
        assert query["client_id"] == [CLIENT] and query["redirect_uri"] == [REDIRECT]
        code = f"code-{len(self.codes)}"
        self.codes[code] = {"challenge": query["code_challenge"][0], "nonce": query["nonce"][0]}
        return f"state={query['state'][0]}&code={code}"


def config(**overrides: Any) -> OidcConfig:
    values: dict[str, Any] = {
        "issuer": ISSUER, "client_id": CLIENT, "client_secret": "cs-secret",
        "redirect_url": REDIRECT, "allowed_hosts": frozenset({"idp.example.invalid"}),
    }  # fmt: skip
    return OidcConfig(**{**values, **overrides})


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeProvider]:
    fake = FakeProvider()
    client = OidcClient(config(), httpx.Client(transport=httpx.MockTransport(fake.handle)))
    monkeypatch.setenv("AUTH_MODE", "oidc")
    get_settings.cache_clear()
    monkeypatch.setattr(signin, "oidc_client", lambda: client)
    yield fake
    monkeypatch.setenv("AUTH_MODE", "demo")
    get_settings.cache_clear()


def test_oidc_sign_in_with_pkce(anonymous: TestClient, provider: FakeProvider) -> None:
    start = anonymous.get("/auth/login?next=/fr/inventory&lang=fr", follow_redirects=False)
    assert start.headers["location"].startswith(f"{ISSUER}/protocol/openid-connect/auth?")
    back = anonymous.get(f"/auth/callback?{provider.authorize(start.headers['location'])}",
                         follow_redirects=False)  # fmt: skip
    assert back.status_code == 303 and back.headers["location"] == "/fr/inventory"
    page = anonymous.get("/en/").text
    assert 'data-user="kc-reviewer"' in page and "Kim Reviewer (fictional)" in page
    assert "Acting as" not in page and 'data-auth-mode="demo"' not in page
    out = anonymous.post("/en/sign-out", follow_redirects=False)
    assert out.headers["location"].startswith(f"{ISSUER}/protocol/openid-connect/logout?")


def test_oidc_refusals(anonymous: TestClient, provider: FakeProvider) -> None:
    def attempt() -> str:
        start = anonymous.get("/auth/login", follow_redirects=False).headers["location"]
        query = provider.authorize(start)
        location = anonymous.get(f"/auth/callback?{query}", follow_redirects=False)
        # The same state twice is refused (single use).
        again = anonymous.get(f"/auth/callback?{query}", follow_redirects=False)
        assert again.headers["location"] == "/en/sign-in?error=oidc"
        return str(location.headers["location"])

    provider.audience = "another-client"
    assert attempt() == "/en/sign-in?error=oidc"
    provider.audience = CLIENT
    provider.nonce_override = "replayed"
    assert attempt() == "/en/sign-in?error=oidc"
    provider.nonce_override = None
    assert attempt() == "/en/"
    assert anonymous.get("/auth/callback?error=access_denied",
                         follow_redirects=False).headers["location"] == "/en/sign-in?error=oidc"  # fmt: skip


def test_oidc_calls_only_allowlisted_https_hosts() -> None:
    assert config().check() == []
    assert "evil.example is not in OIDC_ALLOWED_HOSTS" in " ".join(
        config(issuer="https://evil.example/realms/x").check()
    )
    local = config(issuer="http://keycloak:8080/realms/govhub",
                   allowed_hosts=frozenset({"keycloak"}))  # fmt: skip
    assert any("HTTPS required" in p for p in local.check())
    assert config(issuer="http://keycloak:8080/realms/govhub", allowed_hosts=frozenset({"keycloak"}),
                  allow_insecure_http=True).check() == []  # fmt: skip
    client = OidcClient(config(), httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"issuer": ISSUER,
                                            "jwks_uri": "https://elsewhere.example/certs"}))))  # fmt: skip
    with pytest.raises(OidcError, match=r"elsewhere\.example is not in OIDC_ALLOWED_HOSTS"):
        client.verify_id_token(jwt.encode({"a": 1}, "k" * 32, algorithm="HS256"))


# --- startup refusals -------------------------------------------------------------------


def _settings(**values: Any) -> Settings:
    base = get_settings().model_dump()
    return Settings.model_validate({**base, **values})


def test_demo_mode_refuses_a_public_address(cc_db: Session) -> None:
    seed(cc_db, ROOT / "data/demo/tenants.toml")
    check(_settings(auth_mode="demo"), "127.0.0.1", cc_db)  # allowed
    with pytest.raises(StartupRefusedError, match=r"bound to 0\.0\.0\.0"):
        check(_settings(auth_mode="demo", internal_only=False), "0.0.0.0", cc_db)  # noqa: S104
    check(_settings(auth_mode="demo", internal_only=True), "0.0.0.0", cc_db)  # noqa: S104


def test_demo_mode_refuses_a_real_tenant(cc_db: Session) -> None:
    seed(cc_db, ROOT / "data/demo/tenants.toml")
    cc_db.add(Tenant(id="dept-real", name_en="R", name_fr="R", synthetic=False,
                     residency="ca-protected-b", created_by="test"))  # fmt: skip
    cc_db.commit()
    with pytest.raises(StartupRefusedError, match=r"tenants not marked synthetic: dept-real"):
        check(_settings(auth_mode="demo"), "127.0.0.1", cc_db)


def test_oidc_mode_refuses_an_incomplete_configuration(cc_db: Session) -> None:
    with pytest.raises(StartupRefusedError, match="OIDC_ISSUER is not set"):
        check(_settings(auth_mode="oidc"), "0.0.0.0", cc_db)  # noqa: S104
    with pytest.raises(StartupRefusedError, match=r"AUTH_MODE must be oidc or demo"):
        check(_settings(auth_mode="none"), "127.0.0.1", cc_db)


def test_keycloak_realm_matches_the_demo_users() -> None:
    """The local/CI Keycloak realm has the demo users with the same roles (via groups)."""
    import runpy

    script = runpy.run_path(str(ROOT / "scripts/make_keycloak_realm.py"))
    assert script["main"](["--check"]) == 0
    realm = json.loads((ROOT / "docker/keycloak/govhub-realm.json").read_text("utf-8"))
    roles = RoleMap.from_file(ROOT / "data/config/oidc-roles.toml")
    from control_centre.identity.demo_users import demo_users

    people = demo_users(str(ROOT / "data/demo/users.toml"))
    for kc in realm["users"]:
        who = roles.principal({"preferred_username": kc["username"], "groups": kc["groups"]})
        assert who.platform_roles == people[kc["username"]].platform_roles
        assert who.tenant_roles == people[kc["username"]].tenant_roles
    (client,) = realm["clients"]
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert client["directAccessGrantsEnabled"] is False
