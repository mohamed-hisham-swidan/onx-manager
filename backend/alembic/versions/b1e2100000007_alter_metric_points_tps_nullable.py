"""alter metric_points tps nullable

Revision ID: b1e2100000007
Revises: b1e2100000006
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1e2100000007"
down_revision: str | None = "b1e2100000006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("metric_points") as batch_op:
        batch_op.alter_column(
            "tps",
            existing_type=sa.Float(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("metric_points") as batch_op:
        batch_op.alter_column(
            "tps",
            existing_type=sa.Float(),
            nullable=False,
        )
