"""Tenant columns on every tenant-data table; rights for the app role.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from govhub_shared.dbroles import grant_app_role_sql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "evidence_documents", "evidence_passages", "system_facts", "assessments",
    "assessment_results_documents",
)  # fmt: skip


def upgrade() -> None:
    # Rows stored before Milestone 7 keep NULL (visible to no tenant once row-level
    # security is on) until `assessment-engine backfill-tenants` sets them.
    for table in TABLES:
        op.add_column(table, sa.Column("tenant", sa.String(100), nullable=True))
        op.create_index(f"ix_{table}_tenant", table, ["tenant"])
    op.execute(grant_app_role_sql())


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"ix_{table}_tenant", table)
        op.drop_column(table, "tenant")
