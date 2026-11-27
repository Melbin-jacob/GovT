"""Assessments and OSCAL assessment-results documents (immutable).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("assessments", "assessment_results_documents")


def upgrade() -> None:
    op.create_table(
        "assessments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False, index=True),
        sa.Column("finding_id", sa.String(36), nullable=True, index=True),
        sa.Column("system_id", sa.String(64), nullable=False, index=True),
        sa.Column("catalog", sa.String(128), nullable=False),
        sa.Column("catalog_version", sa.String(32), nullable=False),
        sa.Column("control_id", sa.String(64), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("lang", sa.String(8), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("detail", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "assessment_results_documents",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("system_id", sa.String(64), nullable=False, index=True),
        sa.Column("document", JSONB, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        """
        CREATE FUNCTION assessment_engine_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'assessments are immutable (% refused)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION assessment_engine_immutable()"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS assessment_engine_immutable()")
    for table in reversed(TABLES):
        op.drop_table(table)
