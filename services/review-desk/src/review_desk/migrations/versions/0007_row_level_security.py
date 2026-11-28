"""Row-level security on the tenant tables (govhub_shared.tenancy).

Enabled, not forced: the owner (migrations, backfills) is not bound; the services run as
govhub_app and see only the tenants bound to their transaction (none when unset).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-28
"""

from collections.abc import Sequence

from alembic import op

from govhub_shared.tenancy import FUNCTION_SQL, drop_policy_sql, policy_sql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "findings",
    "review_sessions",
    "decision_log",
    "poam_versions",
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
