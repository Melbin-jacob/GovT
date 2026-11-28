"""Who may do what in the assessment engine (docs/access-matrix.md), per system's tenant.

The engine does not own the inventory: it asks the rulebook which tenant a system belongs
to (its own service token, all tenants; cached for a minute), then checks the caller's
role in that tenant. A system the rulebook does not know is "not found".
"""

from __future__ import annotations

import time
from typing import Annotated, Any, Final, Protocol

import httpx
from fastapi import Depends, HTTPException

from govhub_shared.auth import (
    AUDITOR,
    GOVERNANCE_OFFICER,
    PLATFORM_ADMIN,
    REVIEWER,
    SYSTEM_OWNER,
    TENANT_ADMIN,
    Principal,
)
from govhub_shared.auth.client import ServiceAuth, signing_key
from govhub_shared.auth.web import principal, require, require_in_tenant

# Evidence text and facts are the most sensitive: owners, reviewers, auditors (read).
EVIDENCE_READERS: Final = (SYSTEM_OWNER, REVIEWER, AUDITOR)
EVIDENCE_WRITERS: Final = (SYSTEM_OWNER, REVIEWER)
METADATA_READERS: Final = (SYSTEM_OWNER, REVIEWER, TENANT_ADMIN, AUDITOR)
ASSESSORS: Final = (REVIEWER,)
SIGNED_IN: Final = (SYSTEM_OWNER, REVIEWER, TENANT_ADMIN, AUDITOR, GOVERNANCE_OFFICER,
                    PLATFORM_ADMIN)  # fmt: skip
CACHE_SECONDS: Final = 60.0


class SystemDirectory(Protocol):
    def tenant_of(self, system_id: str) -> str | None: ...


class RulebookSystems:
    def __init__(self, base_url: str, http: httpx.Client | None = None) -> None:
        self.http = http or httpx.Client(
            base_url=base_url, timeout=15.0,
            auth=ServiceAuth(signing_key("assessment-engine"), "rulebook", all_tenants=True),
        )  # fmt: skip
        self._cache: dict[str, tuple[float, str | None]] = {}

    def tenant_of(self, system_id: str) -> str | None:
        hit = self._cache.get(system_id)
        if hit is not None and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        resp = self.http.get(f"/systems/{system_id}")
        if resp.status_code == 404:
            tenant = None
        elif resp.status_code >= 400:
            raise HTTPException(503, "the rulebook could not say which tenant owns the system")
        else:
            tenant = str(resp.json()["tenant"])
        self._cache[system_id] = (time.monotonic(), tenant)
        return tenant


_DIRECTORY: dict[str, SystemDirectory] = {}


def get_systems() -> SystemDirectory:
    """Overridden in tests."""
    from assessment_engine.config import get_settings

    if "rulebook" not in _DIRECTORY:
        _DIRECTORY["rulebook"] = RulebookSystems(get_settings().rulebook_url)
    return _DIRECTORY["rulebook"]


Systems = Annotated[SystemDirectory, Depends(get_systems)]
PrincipalDep = Annotated[Principal, Depends(principal)]
AnySignedIn = Annotated[
    Principal, Depends(require(*SIGNED_IN, services=("review-desk", "control-centre-service")))
]
Officer = Annotated[Principal, Depends(require(GOVERNANCE_OFFICER))]
ReviewDeskOnly = Annotated[Principal, Depends(require(services=("review-desk",)))]


def check_system(systems: SystemDirectory, who: Principal, system_id: str,
                 *roles: str) -> str:  # fmt: skip
    """The system's tenant, after checking the caller holds one of ``roles`` there."""
    tenant = systems.tenant_of(system_id)
    if tenant is None:
        raise HTTPException(404, f"system {system_id} not found")
    # Not a member of that tenant at all: "not found"; a member without the role: 403.
    if who.kind == "user" and tenant not in who.tenants:
        raise HTTPException(404, f"system {system_id} not found")
    require_in_tenant(who, tenant, *roles)
    return tenant


def record(value: Any) -> str:
    return str(value)[:128]
