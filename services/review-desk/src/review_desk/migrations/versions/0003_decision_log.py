"""Append-only, hash-chained decision log; UPDATE, DELETE and TRUNCATE are refused.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_log",
        sa.Column("seq", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("uuid", sa.String(36), nullable=False, unique=True),
        sa.Column("finding_id", sa.String(36), nullable=False, index=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("record_text", sa.Text(), nullable=False),
        sa.Column("previous_hash", sa.String(71), nullable=False),
        sa.Column("record_hash", sa.String(71), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.execute(
        """
        CREATE FUNCTION review_desk_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'the decision log is append-only (% refused)', TG_OP
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER decision_log_no_update_delete
        BEFORE UPDATE OR DELETE ON decision_log
        FOR EACH ROW EXECUTE FUNCTION review_desk_append_only();
        """
    )
    op.execute(
        """
        CREATE TRIGGER decision_log_no_truncate
        BEFORE TRUNCATE ON decision_log
        FOR EACH STATEMENT EXECUTE FUNCTION review_desk_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS decision_log_no_truncate ON decision_log")
    op.execute("DROP TRIGGER IF EXISTS decision_log_no_update_delete ON decision_log")
    op.drop_table("decision_log")
    op.execute("DROP FUNCTION IF EXISTS review_desk_append_only()")
