"""The caller, from the internal token (``govhub_shared.auth``), as review-desk records it.

Decision records keep ``{id, role, authorized}``; the role is the one the caller acted in
(reviewer of the finding's tenant), so the hash-chained records keep their shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Depends

from govhub_shared.auth import AUDITOR, REVIEWER, SYSTEM_OWNER, TENANT_ADMIN, Principal
from govhub_shared.auth.web import principal, require_in_tenant

AUTHORIZED_ROLES: Final = frozenset({"reviewer"})
TENANT_READERS: Final = (SYSTEM_OWNER, REVIEWER, TENANT_ADMIN, AUDITOR)


@dataclass(frozen=True)
class Reviewer:
    id: str
    role: str

    @property
    def authorized(self) -> bool:
        return self.role in AUTHORIZED_ROLES

    def as_record(self) -> dict[str, object]:
        return {"id": self.id, "role": self.role, "authorized": self.authorized}


def reviewer_in(who: Principal, tenant: str) -> Reviewer:
    """403 unless ``who`` reviews in ``tenant``; then the reviewer for the record."""
    require_in_tenant(who, tenant, REVIEWER)
    return Reviewer(who.id, REVIEWER)


def visible_tenants(who: Principal) -> frozenset[str] | None:
    """None: every tenant (a service with all-tenants scope); else the caller's."""
    if who.kind == "service":
        return None if who.all_tenants else frozenset()
    return who.tenants_with(*TENANT_READERS)


PrincipalDep = Annotated[Principal, Depends(principal)]
