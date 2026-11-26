"""Initial schema: catalogs, immutable catalog versions, control index.

Revision ID: 0001
Revises:
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalogs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "catalog_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "catalog_id",
            sa.Integer(),
            sa.ForeignKey("catalogs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("major", sa.Integer(), nullable=False),
        sa.Column("minor", sa.Integer(), nullable=False),
        sa.Column("patch", sa.Integer(), nullable=False),
        sa.Column("lang", sa.String(2), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("doc_uuid", sa.String(36), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("derived_from", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("catalog_id", "version", "lang", name="uq_catalog_version_lang"),
        sa.CheckConstraint("lang IN ('en', 'fr')", name="ck_catalog_versions_lang"),
    )
    op.create_index(
        "ix_catalog_versions_order",
        "catalog_versions",
        ["catalog_id", "lang", "major", "minor", "patch"],
    )
    op.create_table(
        "catalog_controls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "version_id",
            sa.Integer(),
            sa.ForeignKey("catalog_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("control_id", sa.String(200), nullable=False),
        sa.Column("group_id", sa.String(200), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("version_id", "control_id", name="uq_catalog_controls_version_control"),
        sa.CheckConstraint("status IN ('active', 'withdrawn')", name="ck_catalog_controls_status"),
    )
    op.create_index("ix_catalog_controls_control_id", "catalog_controls", ["control_id"])

    # Stored versions are immutable: refuse UPDATE and DELETE at the database level.
    op.execute(
        """
        CREATE FUNCTION rulebook_forbid_version_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'catalog versions are immutable (% on catalog_versions)', TG_OP
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER catalog_versions_immutable
        BEFORE UPDATE OR DELETE ON catalog_versions
        FOR EACH ROW EXECUTE FUNCTION rulebook_forbid_version_change();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS catalog_versions_immutable ON catalog_versions")
    op.execute("DROP FUNCTION IF EXISTS rulebook_forbid_version_change()")
    op.drop_table("catalog_controls")
    op.drop_table("catalog_versions")
    op.drop_table("catalogs")
