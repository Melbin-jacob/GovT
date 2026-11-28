"""Database roles: migrations run as the owner; services run as ``govhub_app``, which owns
nothing and cannot bypass row-level security (Milestone 7). A deployment creates the role
(with its own password); migrations only grant it table rights when it exists.

Each service reads two URLs: ``*_DATABASE_URL`` (runtime, the app role) and
``*_MIGRATION_DATABASE_URL`` (the owner; defaults to the runtime URL for local runs where
one role does both).
"""

from __future__ import annotations

import re
from typing import Final

APP_ROLE: Final = "govhub_app"


def grant_app_role_sql(role: str = APP_ROLE) -> str:
    """Grant the app role use of every table and sequence (now and future), if it exists."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError(f"not a plain role name: {role!r}")
    # DDL cannot take bind parameters: the role name is validated above.
    return _GRANT.replace("ROLE", role)


_GRANT = """
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ROLE') THEN
            EXECUTE 'GRANT USAGE ON SCHEMA public TO ROLE';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ROLE';
            EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ROLE';
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public
                     GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ROLE';
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public
                     GRANT USAGE, SELECT ON SEQUENCES TO ROLE';
        END IF;
    END $$;
    """
