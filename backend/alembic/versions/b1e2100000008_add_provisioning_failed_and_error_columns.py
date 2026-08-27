"""add provisioning_failed status support and provisioning error columns

Revision ID: b1e2100000008
Revises: b1e2100000007
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1e2100000008"
down_revision: str | None = "b1e2100000007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("servers") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(16),
            type_=sa.String(32),
            nullable=False,
            existing_server_default="created",
        )
        batch_op.add_column(
            sa.Column("provisioning_error", sa.Text(), nullable=True),
        )
        batch_op.add_column(
            sa.Column(
                "provisioning_retryable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("servers") as batch_op:
        batch_op.drop_column("provisioning_retryable")
        batch_op.drop_column("provisioning_error")
        batch_op.alter_column(
            "status",
            existing_type=sa.String(32),
            type_=sa.String(16),
            nullable=False,
            existing_server_default="created",
        )
