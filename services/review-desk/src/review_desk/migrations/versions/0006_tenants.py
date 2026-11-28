"""Tenant on every tenant-data table; rights for the app role.

The decision log's tenant is a generated column read from each record's own text, so no
stored record is ever updated (the log stays append-only).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from govhub_shared.dbroles import grant_app_role_sql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("review_sessions", sa.Column("tenant", sa.String(100), nullable=True))
    op.execute(
        "UPDATE review_sessions s SET tenant = f.tenant FROM findings f WHERE f.id = s.finding_id"
    )
    op.add_column("poam_versions", sa.Column("tenant", sa.String(100), nullable=True))
    # poam_versions are immutable (trigger): fill existing rows with the trigger off.
    op.execute("ALTER TABLE poam_versions DISABLE TRIGGER USER")
    op.execute(
        "UPDATE poam_versions p SET tenant = (SELECT f.tenant FROM findings f "
        "WHERE f.system_id = p.system_id LIMIT 1)"
    )
    op.execute("ALTER TABLE poam_versions ENABLE TRIGGER USER")
    op.execute(
        "ALTER TABLE decision_log ADD COLUMN tenant varchar(100) "
        "GENERATED ALWAYS AS ((record_text::jsonb) ->> 'tenant') STORED"
    )
    for table in ("review_sessions", "poam_versions", "decision_log"):
        op.create_index(f"ix_{table}_tenant", table, ["tenant"])
    op.execute(grant_app_role_sql())


def downgrade() -> None:
    for table in ("review_sessions", "poam_versions", "decision_log"):
        op.drop_index(f"ix_{table}_tenant", table)
        op.drop_column(table, "tenant")
