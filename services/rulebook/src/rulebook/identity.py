"""The caller of the drafting endpoints, from the internal token (``govhub_shared.auth``).

The drafting rules work with one "acting role" per person: the assessment engine's
service identity, else governance-officer (platform-wide), else reviewer (in any tenant).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from govhub_shared.auth import GOVERNANCE_OFFICER, REVIEWER, Principal
from govhub_shared.auth.web import principal

APPROVER_ROLE = "governance-officer"
EDITOR_ROLES = frozenset({"reviewer", "governance-officer"})
ENGINE_ROLE = "assessment-engine"


@dataclass(frozen=True)
class Actor:
    id: str
    role: str


def actor_of(who: Principal) -> Actor:
    if who.kind == "service":
        return Actor(who.id, ENGINE_ROLE if who.id == "assessment-engine" else who.id)
    for role in (GOVERNANCE_OFFICER, REVIEWER):
        if who.has(role):
            return Actor(who.id, role)
    return Actor(who.id, "none")


def current_actor(who: Annotated[Principal, Depends(principal)]) -> Actor:
    return actor_of(who)


ActorDep = Annotated[Actor, Depends(current_actor)]
