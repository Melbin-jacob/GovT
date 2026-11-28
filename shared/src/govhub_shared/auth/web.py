"""The request check every service uses: a bearer token for this service, then roles.

``AuthContext`` holds this service's audience and its trust file. ``principal`` reads the
``Authorization: Bearer`` header (401 when missing or refused, with the refusal code,
never the token); ``require(...)`` refuses with 403 ``role`` unless the caller holds one
of the roles (in any of its tenants, or platform-wide) or is one of the named services.
Tenant-specific checks happen where the tenant is known (``require_in_tenant``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from govhub_shared.auth.principal import Principal
from govhub_shared.auth.tokens import TokenError, TrustStore, verify


@dataclass
class AuthContext:
    audience: str
    trust: TrustStore


def _context(request: Request) -> AuthContext:
    context = getattr(request.app.state, "auth", None)
    if not isinstance(context, AuthContext):
        raise HTTPException(503, "authentication is not configured")
    return context


def principal(request: Request) -> Principal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            401, {"code": "no-token", "message": "sign-in required"},
            headers={"WWW-Authenticate": "Bearer"},
        )  # fmt: skip
    context = _context(request)
    try:
        return verify(token.strip(), context.trust, context.audience)
    except TokenError as exc:
        raise HTTPException(
            401, {"code": exc.code, "message": str(exc)},
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc  # fmt: skip


PrincipalDep = Annotated[Principal, Depends(principal)]


def forbidden(message: str, code: str = "role") -> HTTPException:
    return HTTPException(403, {"code": code, "message": message})


def require(*roles: str, services: tuple[str, ...] = ()) -> Callable[..., Principal]:
    """Dependency: the caller holds one of ``roles`` or is one of ``services``."""

    def check(who: PrincipalDep) -> Principal:
        if who.kind == "service":
            if who.id in services:
                return who
            raise forbidden(f"service {who.id} may not call this endpoint")
        if any(who.has(role) for role in roles):
            return who
        raise forbidden(f"needs one of: {', '.join(roles) or 'a service identity'}")

    # Read by scripts/access_matrix.py (the documented matrix must match the code).
    check.govhub_roles = tuple(roles)  # type: ignore[attr-defined]
    check.govhub_services = tuple(services)  # type: ignore[attr-defined]
    return check


def require_in_tenant(who: Principal, tenant: str, *roles: str) -> None:
    """403 unless the caller holds one of ``roles`` in ``tenant`` (a service with
    all-tenants scope passes)."""
    if who.kind == "service" and who.all_tenants:
        return
    if not any(who.has(role, tenant) for role in roles):
        raise forbidden(f"needs one of: {', '.join(roles)} in tenant {tenant}", "tenant")


def install(app: Any, audience: str, trust: TrustStore) -> None:
    app.state.auth = AuthContext(audience=audience, trust=trust)
