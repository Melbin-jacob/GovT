"""Evidence documents and passages.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-27
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
        "evidence_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("system_id", sa.String(64), nullable=False, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("stored_path", sa.String(255), nullable=False),
        sa.Column("encrypted", sa.Boolean, nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("extraction_status", sa.String(16), nullable=False),
        sa.Column("extraction_detail", sa.String(255), nullable=False, server_default=""),
        sa.Column("uploaded_by", sa.String(128), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("system_id", "sha256", name="uq_evidence_system_sha"),
    )
    op.create_table(
        "evidence_passages",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("evidence_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("system_id", sa.String(64), nullable=False, index=True),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("injection_flags", JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_table("evidence_passages")
    op.drop_table("evidence_documents")
