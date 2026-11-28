"""Tests only: connect the way the services do in a deployment, so row-level security
binds the connection.

The test databases are owned by the test user (a superuser in CI), which RLS does not
bind. ``app_role_engine`` logs in as ``govhub_rls_test`` instead: a role with exactly the
app role's rights (``govhub_shared.dbroles``), no ownership, no BYPASSRLS. Creating it
needs CREATEROLE (CI's test user is a superuser; locally, see docs/decisions.md #114).
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from govhub_shared import tenancy
from govhub_shared.dbroles import grant_app_role_sql

RLS_TEST_ROLE: Final = "govhub_rls_test"
# A template, not an f-string: the table name is checked by _table() first.
_COUNT: Final = "SELECT tenant, count(*) FROM TABLE GROUP BY tenant"


def app_role_engine(owner: Engine) -> Engine:
    """An engine on the owner's database, logged in as the test app role."""
    with owner.begin() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
                             {"r": RLS_TEST_ROLE})  # fmt: skip
        if not exists:
            conn.execute(text(f"CREATE ROLE {RLS_TEST_ROLE} LOGIN PASSWORD '{RLS_TEST_ROLE}' "
                              "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"))  # fmt: skip
        conn.execute(text(grant_app_role_sql(RLS_TEST_ROLE)))
    url = owner.url.set(username=RLS_TEST_ROLE, password=RLS_TEST_ROLE)
    return create_engine(url)


def session(engine: Engine, scope: tenancy.Scope = tenancy.NO_TENANTS) -> Session:
    """A session on ``engine`` bound to ``scope`` (default: no tenant)."""
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    tenancy.bind(s, scope)
    return s


def unbound_session(engine: Engine) -> Session:
    """A session nobody bound: the settings are simply absent."""
    return sessionmaker(bind=engine, expire_on_commit=False)()


def tenants_seen(engine: Engine, table: str, scope: tenancy.Scope) -> dict[str, int]:
    """Rows of ``table`` per tenant, as a session bound to ``scope`` sees them."""
    with session(engine, scope) as s:
        rows = s.execute(text(_COUNT.replace("TABLE", _table(table))))
        return {str(t): int(n) for t, n in rows}


def owner_tenants(owner: Engine, table: str) -> dict[str, int]:
    with owner.connect() as conn:
        rows = conn.execute(text(_COUNT.replace("TABLE", _table(table))))
        return {str(t): int(n) for t, n in rows}


def rls_enabled(owner: Engine, table: str) -> tuple[bool, bool]:
    """(relrowsecurity, relforcerowsecurity) for ``table``."""
    with owner.connect() as conn:
        row = conn.execute(
            text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                 "WHERE relname = :t AND relkind = 'r'"), {"t": table},
        ).one()  # fmt: skip
        return bool(row[0]), bool(row[1])


def _table(name: str) -> str:
    if not name.isidentifier() or not name.islower():
        raise ValueError(f"not a table name: {name!r}")
    return name
