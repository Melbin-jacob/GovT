"""Who may call which rulebook endpoint (docs/access-matrix.md), from internal tokens.

Catalogs, sources and profiles are shared (not tenant data); the inventory and impact
reports show only the caller's tenants (a service with all-tenants scope sees all).
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import Depends

from govhub_shared.auth import (
    AUDITOR,
    GOVERNANCE_OFFICER,
    PROFILE_ASSIGNMENT,
    REVIEWER,
    SYSTEM_OWNER,
    TENANT_ADMIN,
    Principal,
)
from govhub_shared.auth.web import forbidden, require

HUB_SERVICES: Final = (
    "assessment-engine",
    "review-desk",
    "connector-hub",
    "control-centre-service",
)
TENANT_READERS: Final = (SYSTEM_OWNER, REVIEWER, TENANT_ADMIN, AUDITOR)
SHARED_READERS: Final = (*TENANT_READERS, GOVERNANCE_OFFICER)

# Read shared content: catalogs, controls, diffs, profiles, sources.
ReadShared = Annotated[Principal, Depends(require(*SHARED_READERS, services=HUB_SERVICES))]
# Change shared content: catalogs, retirements, profiles, sources.
GovernContent = Annotated[Principal, Depends(require(GOVERNANCE_OFFICER))]
# Tenant data (inventory systems), filtered to the caller's tenants.
ReadTenantData = Annotated[Principal, Depends(require(*TENANT_READERS, services=HUB_SERVICES))]
# Impact reports: tenant roles and governance officers (systems filtered per caller).
ReadImpact = Annotated[
    Principal, Depends(require(*TENANT_READERS, GOVERNANCE_OFFICER, services=HUB_SERVICES))
]
# The inventory snapshot replaces every tenant's systems: connector-hub's sync job only.
SyncInventory = Annotated[Principal, Depends(require(services=("connector-hub",)))]
# Profile assignment: the tenant-admin capability, checked per system's tenant.
AssignProfiles = Annotated[Principal, Depends(require(TENANT_ADMIN))]


read_shared = require(*SHARED_READERS, services=HUB_SERVICES)
govern_content = require(GOVERNANCE_OFFICER)
govern_drafts = require(GOVERNANCE_OFFICER)
edit_drafts = require(REVIEWER, GOVERNANCE_OFFICER)
read_drafts = require(REVIEWER, GOVERNANCE_OFFICER, AUDITOR, services=("assessment-engine",))
engine_drafts = require(services=("assessment-engine",))
audit_drafts = require(GOVERNANCE_OFFICER, AUDITOR)


def visible_tenants(who: Principal) -> frozenset[str] | None:
    """None: every tenant (a service job with all-tenants scope); else the caller's."""
    if who.kind == "service":
        return None if who.all_tenants else frozenset()
    return who.tenants_with(*TENANT_READERS)


def require_sync_scope(who: Principal) -> None:
    if not who.all_tenants:
        raise forbidden("the inventory sync needs the all-tenants scope", "scope")


def require_assignment(who: Principal, tenant: str) -> None:
    if not who.can(PROFILE_ASSIGNMENT, tenant):
        raise forbidden(
            f"choosing profiles for {tenant}'s systems needs its tenant-admin", "tenant"
        )
