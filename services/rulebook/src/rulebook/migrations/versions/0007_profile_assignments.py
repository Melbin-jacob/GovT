"""Profile assignments chosen by each tenant's tenant-admin.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profile_assignments",
        sa.Column("system_id", sa.String(100), primary_key=True),
        sa.Column("tenant", sa.String(100), nullable=False, index=True),
        sa.Column("profiles", ARRAY(sa.String(200)), nullable=False),
        sa.Column("set_by", sa.String(200), nullable=False),
        sa.Column(
            "set_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("profile_assignments")
