"""The app role (services at runtime) gets table rights from the migrations; it owns
nothing and cannot bypass row-level security."""

from __future__ import annotations

from sqlalchemy import Engine, text

from govhub_shared.dbroles import APP_ROLE, grant_app_role_sql


def ensure_app_role(engine: Engine) -> None:
    with engine.begin() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": APP_ROLE})
        if not exists:
            conn.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_ROLE}' "
                              "NOSUPERUSER NOBYPASSRLS"))  # fmt: skip


def test_app_role_rights(engine: Engine) -> None:
    ensure_app_role(engine)
    with engine.begin() as conn:
        conn.execute(text(grant_app_role_sql()))
        role = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :r"), {"r": APP_ROLE}
        ).one()
        assert tuple(role) == (False, False)
        for table in ("ai_systems", "approval_log", "draft_views", "profile_assignments"):
            for privilege in ("SELECT", "INSERT"):
                assert conn.scalar(
                    text("SELECT has_table_privilege(:r, :t, :p)"),
                    {"r": APP_ROLE, "t": table, "p": privilege},
                ), (table, privilege)
            owner = conn.scalar(text("SELECT tableowner FROM pg_tables WHERE tablename = :t"),
                                {"t": table})  # fmt: skip
            assert owner != APP_ROLE


def test_role_names_are_validated() -> None:
    import pytest

    with pytest.raises(ValueError, match="not a plain role name"):
        grant_app_role_sql("x; DROP TABLE y")
