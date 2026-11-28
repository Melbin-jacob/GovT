"""Tenants.

Revision ID: 0001
Revises:
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name_en", sa.String(300), nullable=False),
        sa.Column("name_fr", sa.String(300), nullable=False),
        sa.Column("synthetic", sa.Boolean, nullable=False),
        sa.Column("residency", sa.String(40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.CheckConstraint(
            "residency IN ('ca-only', 'ca-protected-b', 'unrestricted-synthetic')",
            name="tenants_residency_label",
        ),
        sa.CheckConstraint(
            "residency <> 'unrestricted-synthetic' OR synthetic", name="tenants_synthetic_label"
        ),
    )


def downgrade() -> None:
    op.drop_table("tenants")
