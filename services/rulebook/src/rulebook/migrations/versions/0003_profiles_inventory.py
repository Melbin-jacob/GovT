"""Stored profiles and the AI-system inventory (snapshots).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("name", sa.String(200), primary_key=True),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("updated_by", sa.String(200), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "inventory_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("imported_by", sa.String(200), nullable=False),
        sa.Column(
            "imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "ai_systems",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            sa.ForeignKey("inventory_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("system_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("tenant", sa.String(100), nullable=False),
        sa.Column("department", sa.String(300), nullable=False),
        sa.Column("owner", sa.String(300), nullable=False),
        sa.Column("owner_email", sa.String(300), nullable=False),
        sa.Column("impact_level", sa.Integer(), nullable=False),
        sa.Column("lifecycle", sa.String(20), nullable=False),
        sa.Column("profiles", postgresql.ARRAY(sa.String(200)), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("snapshot_id", "system_id", name="uq_ai_systems_snapshot_system"),
        sa.CheckConstraint("impact_level BETWEEN 1 AND 4", name="ck_ai_systems_impact_level"),
    )
    op.create_index("ix_ai_systems_tenant", "ai_systems", ["tenant"])


def downgrade() -> None:
    op.drop_table("ai_systems")
    op.drop_table("inventory_snapshots")
    op.drop_table("profiles")
