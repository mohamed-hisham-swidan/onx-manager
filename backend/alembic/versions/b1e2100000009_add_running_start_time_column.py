"""add running_start_time column

Revision ID: b1e2100000009
Revises: b1e2100000008
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1e2100000009"
down_revision: str | None = "b1e2100000008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("servers") as batch_op:
        batch_op.add_column(
            sa.Column("running_start_time", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("servers") as batch_op:
        batch_op.drop_column("running_start_time")
