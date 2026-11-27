"""Immutable POA&M versions (one OSCAL document per system and version).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "poam_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("system_id", sa.String(100), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("system_id", "version", name="uq_poam_system_version"),
    )
    op.execute(
        """
        CREATE TRIGGER poam_versions_immutable
        BEFORE UPDATE OR DELETE ON poam_versions
        FOR EACH ROW EXECUTE FUNCTION review_desk_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS poam_versions_immutable ON poam_versions")
    op.drop_table("poam_versions")
