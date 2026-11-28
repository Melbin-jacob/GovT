"""Internal tokens: signing, key rotation, audience, expiry and skew, issuer kinds."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from govhub_shared.auth import (
    GOVERNANCE_OFFICER,
    LEEWAY,
    PROFILE_ASSIGNMENT,
    REVIEWER,
    TENANT_ADMIN,
    Principal,
    TokenError,
    TrustStore,
    generate_key,
    mint,
    verify,
)
from govhub_shared.auth.demo_guard import DemoModeRefusedError, check, internal_bind
from govhub_shared.auth.web import PrincipalDep, install, require

NOW = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
CC = generate_key("control-centre", "cc-2026-11")
ENGINE = generate_key("assessment-engine", "engine-1")
ALICE = Principal(
    kind="user",
    id="u-alice",
    name="Alice Fictional",
    tenant_roles={"office-a": frozenset({REVIEWER}), "office-b": frozenset({TENANT_ADMIN})},
)
OFFICER = Principal(kind="user", id="u-gov", platform_roles=frozenset({GOVERNANCE_OFFICER}))
ENGINE_ID = Principal(kind="service", id="assessment-engine")


def trust() -> TrustStore:
    store = TrustStore()
    store.add("control-centre", "user", CC.kid, CC.public_pem())
    store.add("assessment-engine", "service", ENGINE.kid, ENGINE.public_pem())
    return store


def refused(token: str, store: TrustStore | None = None, aud: str = "review-desk",
            at: datetime = NOW) -> str:  # fmt: skip
    with pytest.raises(TokenError) as err:
        verify(token, store or trust(), aud, now=at)
    return err.value.code


def test_round_trip_keeps_roles_per_tenant() -> None:
    who = verify(mint(CC, ALICE, "review-desk", now=NOW), trust(), "review-desk", now=NOW)
    assert who == ALICE
    assert who.has(REVIEWER, "office-a") and not who.has(REVIEWER, "office-b")
    assert who.can(PROFILE_ASSIGNMENT, "office-b") and not who.can(PROFILE_ASSIGNMENT, "office-a")
    assert who.tenants_with(TENANT_ADMIN) == {"office-b"}


def test_wrong_audience_is_refused() -> None:
    token = mint(CC, ALICE, "rulebook", now=NOW)
    assert refused(token, aud="review-desk") == "audience"
    assert verify(token, trust(), "rulebook", now=NOW).id == "u-alice"


def test_key_rotation() -> None:
    """A new key is trusted alongside the old one, then the old one is withdrawn."""
    new = generate_key("control-centre", "cc-2026-12")
    store = trust()
    old_token = mint(CC, ALICE, "rulebook", now=NOW)
    new_token = mint(new, ALICE, "rulebook", now=NOW)
    assert refused(new_token, store, "rulebook") == "key"  # not trusted yet
    store.add("control-centre", "user", new.kid, new.public_pem())
    for token in (old_token, new_token):  # overlap: both accepted
        assert verify(token, store, "rulebook", now=NOW).id == "u-alice"
    store.remove("control-centre", CC.kid)
    assert refused(old_token, store, "rulebook") == "key"
    assert verify(new_token, store, "rulebook", now=NOW).id == "u-alice"
    # The trust file round-trips (public keys only).
    text = json.dumps(store.to_json())
    assert "PRIVATE" not in text
    assert verify(new_token, TrustStore.from_json(json.loads(text)), "rulebook", now=NOW)


def test_a_key_id_cannot_be_borrowed_by_another_issuer() -> None:
    forged = generate_key("control-centre", CC.kid)  # same kid, different private key
    assert refused(mint(forged, ALICE, "review-desk", now=NOW)) == "signature"


def test_expiry_with_clock_skew() -> None:
    token = mint(CC, ALICE, "review-desk", now=NOW)
    end = NOW + timedelta(minutes=5)
    assert verify(token, trust(), "review-desk", now=end + LEEWAY - timedelta(seconds=1))
    assert refused(token, at=end + LEEWAY) == "expired"
    # A clock running slightly behind still accepts a fresh token; far behind does not.
    assert verify(token, trust(), "review-desk", now=NOW - LEEWAY + timedelta(seconds=1))
    assert refused(token, at=NOW - LEEWAY - timedelta(seconds=1)) == "not-yet-valid"
    with pytest.raises(ValueError, match="at most 5 minutes"):
        mint(CC, ALICE, "review-desk", ttl=timedelta(minutes=6))


def test_issuer_kinds() -> None:
    # A service speaks for itself only, and only a service may claim all tenants.
    job = Principal(kind="service", id="assessment-engine", all_tenants=True)
    assert verify(mint(ENGINE, job, "review-desk", now=NOW), trust(), "review-desk", now=NOW)
    pretending = Principal(kind="service", id="connector-hub")
    assert refused(mint(ENGINE, pretending, "review-desk", now=NOW)) == "subject"
    assert refused(mint(ENGINE, ALICE, "review-desk", now=NOW)) == "kind"
    greedy = ALICE.model_copy(update={"all_tenants": True})
    assert refused(mint(CC, greedy, "review-desk", now=NOW)) == "scope"
    stranger = generate_key("somebody")
    assert refused(mint(stranger, ALICE, "review-desk", now=NOW)) == "issuer"


def test_only_es256_and_known_roles() -> None:
    claims = {"iss": "control-centre", "sub": "x", "aud": "review-desk", "kind": "user",
              "iat": int(NOW.timestamp()), "nbf": int(NOW.timestamp()),
              "exp": int(NOW.timestamp()) + 60}  # fmt: skip
    hmac = jwt.encode(claims, "secret-secret-secret-secret-secret", algorithm="HS256",
                      headers={"kid": CC.kid, "typ": "govhub+jwt"})  # fmt: skip
    assert refused(hmac) == "algorithm"
    assert refused("not.a.token") == "malformed"
    bad = Principal(kind="user", id="u", tenant_roles={"office-a": frozenset({"root"})})
    assert refused(mint(CC, bad, "review-desk", now=NOW)) == "claims"
    misplaced = Principal(kind="user", id="u", tenant_roles={"a": frozenset({GOVERNANCE_OFFICER})})
    assert refused(mint(CC, misplaced, "review-desk", now=NOW)) == "claims"


def test_request_check() -> None:
    app = FastAPI()
    install(app, "review-desk", trust())

    @app.get("/me")
    def me(who: PrincipalDep) -> dict[str, str]:
        return {"id": who.id}

    @app.get("/officers")
    def officers(who: Principal = Depends(require(GOVERNANCE_OFFICER))) -> dict[str, str]:  # noqa: B008
        return {"id": who.id}

    @app.get("/engine")
    def engine(
        who: Principal = Depends(require(services=("assessment-engine",))),  # noqa: B008
    ) -> dict[str, str]:
        return {"id": who.id}

    client = TestClient(app)

    def get(path: str, who: Principal, key: object = CC) -> int:
        token = mint(key, who, "review-desk")  # type: ignore[arg-type]
        return client.get(path, headers={"Authorization": f"Bearer {token}"}).status_code

    none = client.get("/me")
    assert none.status_code == 401 and none.json()["detail"]["code"] == "no-token"
    wrong = client.get("/me", headers={"Authorization": f"Bearer {mint(CC, ALICE, 'rulebook')}"})
    assert wrong.status_code == 401 and wrong.json()["detail"]["code"] == "audience"
    assert get("/me", ALICE) == 200
    assert get("/officers", ALICE) == 403 and get("/officers", OFFICER) == 200
    assert get("/engine", OFFICER) == 403 and get("/engine", ENGINE_ID, ENGINE) == 200


@pytest.mark.parametrize(
    ("host", "internal_only", "allowed"),
    [
        ("127.0.0.1", False, True),
        ("localhost", False, True),
        ("10.0.4.7", False, True),
        ("::1", False, True),
        ("0.0.0.0", False, False),  # noqa: S104 - a value under test
        ("0.0.0.0", True, True),  # noqa: S104
        ("203.0.113.9", True, False),
        ("my-public-host", True, False),
    ],
)
def test_internal_bind(host: str, internal_only: bool, allowed: bool) -> None:
    assert internal_bind(host, internal_only) is allowed


def test_demo_mode_refuses_a_public_bind() -> None:
    with pytest.raises(DemoModeRefusedError, match=r"bound to 203\.0\.113\.9"):
        check("demo", "203.0.113.9", False, [("office-a", True)])


def test_demo_mode_refuses_a_real_tenant() -> None:
    with pytest.raises(DemoModeRefusedError, match="not marked synthetic: dept-real"):
        check("demo", "127.0.0.1", False, [("office-a", True), ("dept-real", False)])


def test_demo_mode_allowed_and_oidc_unaffected() -> None:
    check("demo", "127.0.0.1", False, [("office-a", True)])
    check("oidc", "203.0.113.9", False, [("dept-real", False)])


def test_dev_keys(tmp_path: object) -> None:
    from pathlib import Path

    from govhub_shared.auth.devkeys import generate
    from govhub_shared.auth.tokens import SigningKey

    folder = Path(str(tmp_path)) / "keys"
    generate(folder)
    store = TrustStore.from_file(folder / "trust.json")
    kid = (folder / "rulebook.kid").read_text("utf-8").strip()
    key = SigningKey.from_file("rulebook", kid, folder / "rulebook.pem")
    who = verify(mint(key, Principal(kind="service", id="rulebook"), "review-desk"), store,
                 "review-desk")  # fmt: skip
    assert who.id == "rulebook"
    assert (folder / "rulebook.pem").stat().st_mode & 0o077 == 0
    assert "PRIVATE" not in (folder / "trust.json").read_text("utf-8")
