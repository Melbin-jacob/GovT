"""Draft reading: approval sessions and recorded views of each language's draft.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "draft_items",
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "draft_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(200), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "draft_views",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("draft_sessions.id"), index=True),
        sa.Column("item_id", sa.String(36), sa.ForeignKey("draft_items.id"), index=True),
        sa.Column("lang", sa.String(2), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Views are evidence of reading: append-only, like the approval log.
    op.execute(
        """
        CREATE FUNCTION rulebook_draft_views_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'draft_views is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER draft_views_no_update_delete BEFORE UPDATE OR DELETE ON draft_views "
        "FOR EACH ROW EXECUTE FUNCTION rulebook_draft_views_append_only()"
    )
    op.execute(
        "CREATE TRIGGER draft_views_no_truncate BEFORE TRUNCATE ON draft_views "
        "FOR EACH STATEMENT EXECUTE FUNCTION rulebook_draft_views_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS draft_views_no_truncate ON draft_views")
    op.execute("DROP TRIGGER IF EXISTS draft_views_no_update_delete ON draft_views")
    op.execute("DROP FUNCTION IF EXISTS rulebook_draft_views_append_only()")
    op.drop_table("draft_views")
    op.drop_table("draft_sessions")
    op.drop_column("draft_items", "changed_at")
