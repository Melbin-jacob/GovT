"""Placeholder identity for the drafting endpoints (same headers as review-desk).

TODO(control-centre): OIDC sign-in and central roles. Until then anyone who can reach the
rulebook can set these headers, so it must stay on localhost or the internal network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException

APPROVER_ROLE = "governance-officer"
EDITOR_ROLES = frozenset({"reviewer", "governance-officer"})
ENGINE_ROLE = "assessment-engine"


@dataclass(frozen=True)
class Actor:
    id: str
    role: str


def current_actor(
    user: Annotated[str | None, Header(alias="X-GovHub-User")] = None,
    role: Annotated[str | None, Header(alias="X-GovHub-Role")] = None,
) -> Actor:
    if not user or not role:
        raise HTTPException(401, "missing X-GovHub-User / X-GovHub-Role (placeholder identity)")
    return Actor(user, role)


ActorDep = Annotated[Actor, Depends(current_actor)]
