"""Who is calling: a person (roles per tenant) or a service (its own name)."""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import BaseModel, Field

SYSTEM_OWNER: Final = "system-owner"
REVIEWER: Final = "reviewer"
GOVERNANCE_OFFICER: Final = "governance-officer"
TENANT_ADMIN: Final = "tenant-admin"
AUDITOR: Final = "auditor"
PLATFORM_ADMIN: Final = "platform-admin"
ROLES: Final = (SYSTEM_OWNER, REVIEWER, GOVERNANCE_OFFICER, TENANT_ADMIN, AUDITOR, PLATFORM_ADMIN)
# Held for the whole platform (shared catalogs and drafts; operations), never per tenant.
PLATFORM_ROLES: Final = frozenset({GOVERNANCE_OFFICER, PLATFORM_ADMIN})
TENANT_ROLES: Final = frozenset(ROLES) - PLATFORM_ROLES
# Tenant-scoped capability: choose which profiles apply to the tenant's systems.
PROFILE_ASSIGNMENT: Final = "profile-assignment"
CAPABILITIES: Final = {TENANT_ADMIN: frozenset({PROFILE_ASSIGNMENT})}


class Principal(BaseModel):
    kind: Literal["user", "service"]
    id: str
    name: str = ""
    platform_roles: frozenset[str] = frozenset()
    tenant_roles: dict[str, frozenset[str]] = Field(default_factory=dict)
    # Service jobs only (task sync, retention, inventory sync): every tenant, logged.
    all_tenants: bool = False
    # Break-glass: the grant that put a tenant in this token (platform-admin only).
    grant: str | None = None

    @property
    def tenants(self) -> frozenset[str]:
        return frozenset(self.tenant_roles)

    def has(self, role: str, tenant: str | None = None) -> bool:
        if role in PLATFORM_ROLES:
            return role in self.platform_roles
        if tenant is None:
            return any(role in roles for roles in self.tenant_roles.values())
        return role in self.tenant_roles.get(tenant, frozenset())

    def can(self, capability: str, tenant: str) -> bool:
        return any(capability in CAPABILITIES.get(r, frozenset()) for r in
                   self.tenant_roles.get(tenant, frozenset()))  # fmt: skip

    def tenants_with(self, *roles: str) -> frozenset[str]:
        return frozenset(t for t, held in self.tenant_roles.items() if held & set(roles))

    def claims(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "name": self.name,
            "platform_roles": sorted(self.platform_roles),
            "tenant_roles": {t: sorted(r) for t, r in sorted(self.tenant_roles.items())},
        }
        if self.all_tenants:
            out["all_tenants"] = True
        if self.grant:
            out["grant"] = self.grant
        return out

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> Principal:
        platform = frozenset(claims.get("platform_roles", []))
        tenant_roles = {str(t): frozenset(r) for t, r in claims.get("tenant_roles", {}).items()}
        unknown = (platform - PLATFORM_ROLES) | {
            r for roles in tenant_roles.values() for r in roles if r not in TENANT_ROLES
        }
        if unknown:
            raise ValueError(f"unknown or misplaced roles: {sorted(unknown)}")
        return cls(
            kind=claims["kind"], id=str(claims["sub"]), name=str(claims.get("name", "")),
            platform_roles=platform, tenant_roles=tenant_roles,
            all_tenants=bool(claims.get("all_tenants", False)), grant=claims.get("grant"),
        )  # fmt: skip
