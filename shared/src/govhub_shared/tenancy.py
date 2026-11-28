"""Row-level security: which tenants a database transaction may see.

Every table holding one tenant's data has a ``tenant`` column and a PostgreSQL policy
that calls ``govhub_tenant_visible(tenant)`` (``policy_sql``). The function reads two
transaction-local settings that this module sets at the start of every transaction of a
bound session (and again after each commit):

- ``govhub.tenants``: comma-separated tenant IDs the caller may see;
- ``govhub.all_tenants``: ``on`` only for a service identity with the all-tenants scope,
  or a platform operation that widens explicitly in code (``widened``).

Nothing set means no rows (fail closed). The services connect as ``govhub_app``, which
does not own the tables and has no BYPASSRLS, so the policies bind it; migrations run as
the owner, which they do not bind (RLS is enabled, not forced). The policies back up the
application's own tenant checks: a missed filter in code returns nothing rather than
another tenant's rows. They do not defend against arbitrary SQL run as the app role.
"""

# No ``from __future__ import annotations`` here: FastAPI reads the dependency's
# annotations at run time, and they refer to the ``get_session`` passed in.

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated, Final

from fastapi import Depends, Request
from sqlalchemy import Connection, event, text
from sqlalchemy.orm import Session, SessionTransaction

from govhub_shared.auth.principal import Principal
from govhub_shared.auth.web import principal

Scope = frozenset[str] | None
"""The tenants a transaction may see; None means every tenant."""

ALL_TENANTS: Final[Scope] = None
NO_TENANTS: Final[frozenset[str]] = frozenset()
_KEY: Final = "govhub_tenant_scope"
_TENANT: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_SET: Final = text(
    "SELECT set_config('govhub.tenants', :tenants, true), "
    "set_config('govhub.all_tenants', :all, true)"
)


def visible(who: Principal | None, *roles: str) -> Scope:
    """Every tenant for a service with the all-tenants scope; a user's tenants in which
    they hold one of ``roles``; nothing for anyone else (or no caller)."""
    if who is None:
        return NO_TENANTS
    if who.kind == "service":
        return ALL_TENANTS if who.all_tenants else NO_TENANTS
    return who.tenants_with(*roles)


def _params(scope: Scope) -> dict[str, str]:
    if scope is None:
        return {"tenants": "", "all": "on"}
    bad = sorted(t for t in scope if not _TENANT.fullmatch(t))
    if bad:
        raise ValueError(f"not a tenant ID: {bad}")
    return {"tenants": ",".join(sorted(scope)), "all": "off"}


def _apply(session: Session, _transaction: SessionTransaction, connection: Connection) -> None:
    connection.execute(_SET, _params(session.info.get(_KEY, NO_TENANTS)))


def bind(session: Session, scope: Scope) -> None:
    """Bind ``session`` to ``scope`` now and at the start of every later transaction."""
    _params(scope)  # validate before storing
    session.info[_KEY] = scope
    if not event.contains(session, "after_begin", _apply):
        event.listen(session, "after_begin", _apply)
    if session.in_transaction():
        session.execute(_SET, _params(scope))


def scope_of(session: Session) -> Scope:
    return session.info.get(_KEY, NO_TENANTS)  # type: ignore[no-any-return]


@contextmanager
def widened(session: Session, scope: Scope) -> Iterator[None]:
    """Temporarily see ``scope`` (e.g. every tenant to read a hash chain's head), then
    return to the caller's scope. Every use is a platform operation named in code."""
    before = scope_of(session)
    bind(session, scope)
    try:
        yield
    except BaseException:
        session.info[_KEY] = before  # the failed transaction is rolled back anyway
        raise
    bind(session, before)


def caller_or_none(request: Request) -> Principal | None:
    """The token's caller, or None without an Authorization header (probes). Route
    access is still decided by ``principal`` / ``require`` on each route."""
    if "authorization" not in request.headers:
        return None
    return principal(request)


def tenant_session(
    get_session: Callable[..., Iterator[Session]], scope: Callable[[Principal | None], Scope]
) -> Callable[..., Session]:
    """A FastAPI dependency: the request's session, bound to ``scope(caller)``."""

    def dependency(
        session: Annotated[Session, Depends(get_session)],
        who: Annotated[Principal | None, Depends(caller_or_none)],
    ) -> Session:
        bind(session, scope(who))
        return session

    return dependency


FUNCTION_SQL: Final = """
CREATE OR REPLACE FUNCTION govhub_tenant_visible(t text) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT coalesce(current_setting('govhub.all_tenants', true), '') = 'on'
      OR (t IS NOT NULL AND t = ANY (string_to_array(
            coalesce(current_setting('govhub.tenants', true), ''), ',')))
$$
"""
_TABLE: Final = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def _table(name: str) -> str:
    if not _TABLE.fullmatch(name):
        raise ValueError(f"not a table name: {name!r}")
    return name


def policy_sql(table: str) -> list[str]:
    """Enable row-level security on ``table`` (not forced: the owner is not bound)."""
    t = _table(table)
    return [
        f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation ON {t} "
        "USING (govhub_tenant_visible(tenant)) WITH CHECK (govhub_tenant_visible(tenant))",
    ]


def drop_policy_sql(table: str) -> list[str]:
    t = _table(table)
    return [f"DROP POLICY IF EXISTS tenant_isolation ON {t}",
            f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY"]  # fmt: skip
