"""add_updated_at_to_metric_points

Revision ID: ff9c2b3a8e4d
Revises: 5a50140d37df
Create Date: 2026-07-24 16:33:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ff9c2b3a8e4d"
down_revision: str | None = "5a50140d37df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "metric_points",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("metric_points", "updated_at")
