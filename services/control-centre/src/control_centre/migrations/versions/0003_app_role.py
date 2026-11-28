"""Rights for the app role (services run as govhub_app; migrations as the owner).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-28
"""

from collections.abc import Sequence

from alembic import op

from govhub_shared.dbroles import grant_app_role_sql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(grant_app_role_sql())


def downgrade() -> None:
    pass  # rights are harmless without the tables; the role is the deployment's
