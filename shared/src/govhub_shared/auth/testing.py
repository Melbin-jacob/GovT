"""Test helpers: in-memory keys for every issuer, and Authorization headers.

from govhub_shared.auth.testing import KEYS, headers, user, service
install(app, "review-desk", KEYS.trust)
client.get("/queue", headers=headers(user("u1", reviewer=["office-a"]), "review-desk"))
"""

from __future__ import annotations

from collections.abc import Generator, Iterator, Mapping
from dataclasses import dataclass, field

import httpx

from govhub_shared.auth.devkeys import SERVICE_ISSUERS, USER_ISSUERS
from govhub_shared.auth.principal import Principal
from govhub_shared.auth.tokens import IssuerKind, SigningKey, TrustStore, generate_key, mint


@dataclass
class TestKeys:
    keys: dict[str, SigningKey] = field(default_factory=dict)
    trust: TrustStore = field(default_factory=TrustStore)

    def __post_init__(self) -> None:
        for issuer in (*USER_ISSUERS, *SERVICE_ISSUERS):
            key = generate_key(issuer, f"{issuer}-test")
            self.keys[issuer] = key
            kind: IssuerKind = "user" if issuer in USER_ISSUERS else "service"
            self.trust.add(issuer, kind, key.kid, key.public_pem())


KEYS = TestKeys()


def user(
    id: str = "u-test",
    *,
    platform: tuple[str, ...] = (),
    name: str = "",
    **tenant_roles: list[str],
) -> Principal:
    """``user("u1", reviewer=["office-a"], auditor=["office-a", "office-b"])``; role keyword
    names use underscores (``tenant_admin``, ``system_owner``)."""
    by_tenant: dict[str, set[str]] = {}
    for role, tenants in tenant_roles.items():
        for tenant in tenants:
            by_tenant.setdefault(tenant, set()).add(role.replace("_", "-"))
    return Principal(
        kind="user", id=id, name=name or id, platform_roles=frozenset(platform),
        tenant_roles={t: frozenset(r) for t, r in by_tenant.items()},
    )  # fmt: skip


def service(name: str, *, all_tenants: bool = False) -> Principal:
    return Principal(kind="service", id=name, all_tenants=all_tenants)


def token(who: Principal, audience: str) -> str:
    issuer = "control-centre" if who.kind == "user" else who.id
    return mint(KEYS.keys[issuer], who, audience)


class FreshHeaders(Mapping[str, str]):
    """An Authorization header minted anew whenever it is read (tokens live 5 minutes)."""

    def __init__(self, who: Principal, audience: str) -> None:
        self.who = who
        self.audience = audience

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {token(self.who, self.audience)}"}

    def __getitem__(self, key: str) -> str:
        return self._headers()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._headers())

    def __len__(self) -> int:
        return 1


def headers(who: Principal, audience: str) -> FreshHeaders:
    return FreshHeaders(who, audience)


class DefaultCaller(httpx.Auth):
    """For test clients: sign every request as ``who`` unless it already carries an
    Authorization header (a test choosing another caller)."""

    def __init__(self, who: Principal, audience: str) -> None:
        self.who = who
        self.audience = audience

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        if "authorization" not in request.headers:
            request.headers["Authorization"] = f"Bearer {token(self.who, self.audience)}"
        yield request
