"""Drafted control changes and the hash-chained approval log.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "draft_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("catalog", sa.String(200), nullable=False),
        sa.Column("base_version", sa.String(50), nullable=False),
        sa.Column("instrument", sa.String(200), nullable=False),
        sa.Column("from_version", sa.String(50), nullable=False),
        sa.Column("to_version", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("new_version", sa.String(50), nullable=True),
        sa.Column("plan", JSONB, nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "draft_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("draft_batches.id"), index=True),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("old_clauses", JSONB, nullable=False),
        sa.Column("new_clauses", JSONB, nullable=False),
        sa.Column("target_control", sa.String(200), nullable=True),
        sa.Column("proposed_id", sa.String(200), nullable=True),
        sa.Column("group_key", sa.String(100), nullable=True),
        sa.Column("flags", JSONB, nullable=False),
        sa.Column("drafts", JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_edited_by", sa.String(200), nullable=True),
        sa.Column("decided_by", sa.String(200), nullable=True),
    )
    op.create_table(
        "approval_log",
        sa.Column("seq", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("batch_id", sa.String(36), nullable=False, index=True),
        sa.Column("item_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("record_text", sa.Text, nullable=False),
        sa.Column("previous_hash", sa.String(71), nullable=False),
        sa.Column("record_hash", sa.String(71), nullable=False),
    )
    op.execute(
        """
        CREATE FUNCTION rulebook_approval_log_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'the approval log is append-only (% refused)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER approval_log_no_update_delete BEFORE UPDATE OR DELETE ON approval_log "
        "FOR EACH ROW EXECUTE FUNCTION rulebook_approval_log_append_only()"
    )
    op.execute(
        "CREATE TRIGGER approval_log_no_truncate BEFORE TRUNCATE ON approval_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION rulebook_approval_log_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS approval_log_no_truncate ON approval_log")
    op.execute("DROP TRIGGER IF EXISTS approval_log_no_update_delete ON approval_log")
    op.execute("DROP FUNCTION IF EXISTS rulebook_approval_log_append_only()")
    op.drop_table("approval_log")
    op.drop_table("draft_items")
    op.drop_table("draft_batches")
