"""Structured facts per system (for rule-based checks).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_facts",
        sa.Column("system_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("value", JSONB, nullable=True),
        sa.Column("source", sa.String(255), nullable=False, server_default=""),
        sa.Column("recorded_by", sa.String(128), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("system_facts")
