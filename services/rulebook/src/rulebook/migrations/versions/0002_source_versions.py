"""Source documents: official policy text per instrument, effective date and language.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GENERIC_FN = """
CREATE OR REPLACE FUNCTION rulebook_forbid_version_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'stored versions are immutable (% on %)', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;
"""
_ORIGINAL_FN = """
CREATE OR REPLACE FUNCTION rulebook_forbid_version_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'catalog versions are immutable (% on catalog_versions)', TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "source_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument", sa.String(100), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("lang", sa.String(2), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("instrument", "effective_date", "lang", name="uq_source_version_lang"),
        sa.CheckConstraint("lang IN ('en', 'fr')", name="ck_source_versions_lang"),
    )
    op.execute(_GENERIC_FN)
    op.execute(
        """
        CREATE TRIGGER source_versions_immutable
        BEFORE UPDATE OR DELETE ON source_versions
        FOR EACH ROW EXECUTE FUNCTION rulebook_forbid_version_change();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS source_versions_immutable ON source_versions")
    op.drop_table("source_versions")
    op.execute(_ORIGINAL_FN)
