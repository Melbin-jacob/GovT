"""Findings (review queue) and review sessions (timing).

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

VERDICTS = "('met', 'partially-met', 'not-met', 'not-applicable', 'unable-to-determine')"
STATES = (
    "('open', 'awaiting-evidence', 'accepted', 'accepted-with-remediation', 'rejected', "
    "'overridden')"
)


def upgrade() -> None:
    op.create_table(
        "findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(64), nullable=False, index=True),
        sa.Column("task_id", sa.String(100), nullable=True),
        sa.Column("servicenow_task", sa.String(40), nullable=True),
        sa.Column("system_id", sa.String(100), nullable=False, index=True),
        sa.Column("system_name", sa.String(300), nullable=False),
        sa.Column("tenant", sa.String(100), nullable=False, index=True),
        sa.Column("owner_email", sa.String(300), nullable=True),
        sa.Column("impact_level", sa.String(10), nullable=False),
        sa.Column("catalog", sa.String(200), nullable=False),
        sa.Column("catalog_version", sa.String(50), nullable=False),
        sa.Column("control_id", sa.String(200), nullable=False),
        sa.Column("statement", sa.Text(), nullable=True),
        sa.Column("evidence_requested", sa.Text(), nullable=True),
        sa.Column("reasons", postgresql.JSONB(), nullable=False),
        sa.Column("obligation_change", sa.Boolean(), nullable=False),
        sa.Column("verdict", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("placeholder", sa.Boolean(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("report_id", "system_id", "control_id", name="uq_findings_report"),
        sa.CheckConstraint(f"verdict IN {VERDICTS}", name="ck_findings_verdict"),
        sa.CheckConstraint(f"state IN {STATES}", name="ck_findings_state"),
    )
    op.create_table(
        "review_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "finding_id", sa.String(36), sa.ForeignKey("findings.id"), nullable=False, index=True
        ),
        sa.Column("reviewer", sa.String(200), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_table("review_sessions")
    op.drop_table("findings")
