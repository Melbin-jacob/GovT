"""Internal tokens: ES256 JWTs with a key ID, one audience, 5 minutes, small clock skew.

- Every issuer has one or more keys in the verifier's **trust file**; the key ID (``kid``)
  picks the key, so a new key can be added before the old one is removed (rotation).
- ``aud`` names the one target service; a token for another service is refused.
- Issuers have a **kind**: ``user`` (only control-centre: people signed in, or the
  fictional users of demo mode) or ``service`` (a service speaking for itself; its
  ``sub`` must be its own issuer name, and only service issuers may claim all tenants).
- Only ES256 is accepted (never ``none`` or HMAC).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from govhub_shared.auth.principal import Principal

ALGORITHM: Final = "ES256"
TOKEN_TYPE: Final = "govhub+jwt"  # noqa: S105 - the JWT "typ" value, not a secret
DEFAULT_TTL: Final = timedelta(minutes=5)
LEEWAY: Final = timedelta(seconds=30)
MAX_TTL: Final = timedelta(minutes=5)


class TokenError(ValueError):
    """A token was refused; ``code`` says why (never the token itself)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SigningKey:
    issuer: str
    kid: str
    private_pem: bytes = field(repr=False)

    def public_pem(self) -> str:
        key = serialization.load_pem_private_key(self.private_pem, password=None)
        return (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode("ascii")
        )

    @classmethod
    def from_file(cls, issuer: str, kid: str, path: str | Path) -> SigningKey:
        return cls(issuer, kid, Path(path).read_bytes())


def generate_key(issuer: str, kid: str | None = None) -> SigningKey:
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return SigningKey(issuer, kid or f"{issuer}-{uuid.uuid4().hex[:8]}", pem)


IssuerKind = Literal["user", "service"]


@dataclass
class TrustStore:
    """Public keys per issuer, and what each issuer may issue."""

    issuers: dict[str, tuple[IssuerKind, dict[str, Any]]] = field(default_factory=dict)

    def add(self, issuer: str, kind: IssuerKind, kid: str, public_pem: str) -> None:
        current = self.issuers.get(issuer)
        if current is not None and current[0] != kind:
            raise ValueError(f"issuer {issuer} is already trusted as {current[0]}")
        keys = current[1] if current else {}
        keys[kid] = serialization.load_pem_public_key(public_pem.encode("ascii"))
        self.issuers[issuer] = (kind, keys)

    def remove(self, issuer: str, kid: str) -> None:
        self.issuers[issuer][1].pop(kid, None)

    def to_json(self) -> dict[str, Any]:
        def pem(key: Any) -> str:
            return str(key.public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode("ascii"))  # fmt: skip

        return {
            "format": "govhub-trust/1",
            "issuers": {
                name: {"kind": kind, "keys": {kid: pem(k) for kid, k in keys.items()}}
                for name, (kind, keys) in sorted(self.issuers.items())
            },
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TrustStore:
        if data.get("format") != "govhub-trust/1":
            raise ValueError("not a govhub-trust/1 file")
        store = cls()
        for name, entry in data["issuers"].items():
            if entry["kind"] not in ("user", "service"):
                raise ValueError(f"{name}: kind must be user or service")
            for kid, pem in entry["keys"].items():
                store.add(name, entry["kind"], kid, pem)
        return store

    @classmethod
    def from_file(cls, path: str | Path) -> TrustStore:
        return cls.from_json(json.loads(Path(path).read_text("utf-8")))


def _now() -> datetime:
    return datetime.now(UTC)


def mint(
    key: SigningKey,
    principal: Principal,
    audience: str,
    *,
    ttl: timedelta = DEFAULT_TTL,
    now: datetime | None = None,
) -> str:
    if ttl > MAX_TTL or ttl <= timedelta(0):
        raise ValueError("internal tokens live at most 5 minutes")
    issued = now or _now()
    claims = {
        **principal.claims(),
        "iss": key.issuer,
        "sub": principal.id,
        "aud": audience,
        "iat": int(issued.timestamp()),
        "nbf": int(issued.timestamp()),
        "exp": int((issued + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(
        claims, key.private_pem, algorithm=ALGORITHM, headers={"kid": key.kid, "typ": TOKEN_TYPE}
    )


def verify(
    token: str, trust: TrustStore, audience: str, *, now: datetime | None = None
) -> Principal:
    """The caller, or ``TokenError``. Checks signature, key ID, issuer kind, audience,
    expiry (with ``LEEWAY``), lifetime and roles."""
    try:
        header = jwt.get_unverified_header(token)
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise TokenError("malformed", "the token cannot be read") from exc
    if header.get("alg") != ALGORITHM or header.get("typ") != TOKEN_TYPE:
        raise TokenError("algorithm", "only ES256 internal tokens are accepted")
    issuer = str(unverified.get("iss", ""))
    if issuer not in trust.issuers:
        raise TokenError("issuer", f"issuer {issuer!r} is not trusted")
    kind, keys = trust.issuers[issuer]
    key = keys.get(str(header.get("kid", "")))
    if key is None:
        raise TokenError("key", f"unknown key ID for issuer {issuer}")
    try:
        claims = _decode_at(token, key, audience, issuer, now or _now())
    except jwt.InvalidAudienceError as exc:
        raise TokenError("audience", f"token is not for {audience}") from exc
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("expired", "token expired") from exc
    except jwt.ImmatureSignatureError as exc:
        raise TokenError("not-yet-valid", "token is not valid yet") from exc
    except jwt.InvalidSignatureError as exc:
        raise TokenError("signature", "bad signature") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("invalid", "token refused") from exc
    if claims["exp"] - claims["iat"] > MAX_TTL.total_seconds():
        raise TokenError("lifetime", "token lives longer than 5 minutes")
    if claims.get("kind") != kind:
        raise TokenError("kind", f"issuer {issuer} issues {kind} tokens only")
    if kind == "service" and claims["sub"] != issuer:
        raise TokenError("subject", "a service token must name its own issuer")
    if kind == "user" and claims.get("all_tenants"):
        raise TokenError("scope", "only service identities may claim all tenants")
    try:
        return Principal.from_claims(claims)
    except (KeyError, ValueError) as exc:
        raise TokenError("claims", str(exc)) from exc


def _decode_at(token: str, key: Any, audience: str, issuer: str, at: datetime) -> dict[str, Any]:
    """Verify signature, audience and issuer, then expiry and not-before against ``at``
    with ``LEEWAY`` (one clock, so tests can set it)."""
    claims: dict[str, Any] = jwt.decode(
        token, key, algorithms=[ALGORITHM], audience=audience, issuer=issuer,
        options={"verify_exp": False, "verify_nbf": False, "verify_iat": False,
                 "require": ["exp", "iat", "nbf", "aud", "iss", "sub"]},
    )  # fmt: skip
    t, skew = at.timestamp(), LEEWAY.total_seconds()
    if claims["exp"] + skew <= t:
        raise jwt.ExpiredSignatureError("expired")
    if claims["nbf"] - skew > t:
        raise jwt.ImmatureSignatureError("not yet valid")
    return claims
