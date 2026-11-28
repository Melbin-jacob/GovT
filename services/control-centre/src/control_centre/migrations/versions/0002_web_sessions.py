"""Web sessions and OIDC logins in progress.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "web_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("principal", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "oidc_logins",
        sa.Column("state", sa.String(64), primary_key=True),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("verifier", sa.String(128), nullable=False),
        sa.Column("next_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("oidc_logins")
    op.drop_table("web_sessions")
