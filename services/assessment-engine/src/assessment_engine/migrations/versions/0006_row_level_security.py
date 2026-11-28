"""Row-level security on the tenant tables (govhub_shared.tenancy).

Enabled, not forced: the owner (migrations, backfills) is not bound; the services run as
govhub_app and see only the tenants bound to their transaction (none when unset).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-28
"""

from collections.abc import Sequence

from alembic import op

from govhub_shared.tenancy import FUNCTION_SQL, drop_policy_sql, policy_sql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "evidence_documents",
    "evidence_passages",
    "system_facts",
    "assessments",
    "assessment_results_documents",
)


def upgrade() -> None:
    op.execute(FUNCTION_SQL)
    for table in TABLES:
        for statement in policy_sql(table):
            op.execute(statement)


def downgrade() -> None:
    for table in TABLES:
        for statement in drop_policy_sql(table):
            op.execute(statement)
    # govhub_tenant_visible() stays: harmless, and another service may share the database.
