"""Placeholder reviewer identity.

TODO(control-centre): replace with OIDC (Entra ID compatible) sign-in and central roles.
Until then identity is read from the headers ``X-GovHub-User`` and ``X-GovHub-Role``,
which anyone who can reach the service can set. That is why review-desk must only be
reachable on localhost or the internal network (docs/decisions.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException

AUTHORIZED_ROLES = frozenset({"reviewer", "governance-officer"})


@dataclass(frozen=True)
class Reviewer:
    id: str
    role: str

    @property
    def authorized(self) -> bool:
        return self.role in AUTHORIZED_ROLES

    def as_record(self) -> dict[str, object]:
        return {"id": self.id, "role": self.role, "authorized": self.authorized}


def current_reviewer(
    user: Annotated[str | None, Header(alias="X-GovHub-User")] = None,
    role: Annotated[str | None, Header(alias="X-GovHub-Role")] = None,
) -> Reviewer:
    if not user or not role:
        raise HTTPException(401, "missing X-GovHub-User / X-GovHub-Role (placeholder identity)")
    return Reviewer(user, role)


def authorized_reviewer(reviewer: Annotated[Reviewer, Depends(current_reviewer)]) -> Reviewer:
    if not reviewer.authorized:
        raise HTTPException(403, f"role {reviewer.role!r} may not review findings")
    return reviewer
