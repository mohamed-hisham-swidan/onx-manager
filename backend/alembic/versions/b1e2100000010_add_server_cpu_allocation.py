"""add cpu_cores and cpu_affinity columns

Revision ID: b1e2100000010
Revises: b1e2100000009
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1e2100000010"
down_revision: str | None = "b1e2100000009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("servers") as batch_op:
        batch_op.add_column(
            sa.Column("cpu_cores", sa.Integer(), nullable=True, server_default="0"),
        )
        batch_op.add_column(
            sa.Column("cpu_affinity", sa.String(length=64), nullable=True, server_default=""),
        )


def downgrade() -> None:
    with op.batch_alter_table("servers") as batch_op:
        batch_op.drop_column("cpu_affinity")
        batch_op.drop_column("cpu_cores")
