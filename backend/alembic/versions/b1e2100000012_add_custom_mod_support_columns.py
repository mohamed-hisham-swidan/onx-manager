"""add loader, mod_id, and is_disabled_on_disk columns to plugins

Revision ID: b1e2100000012
Revises: b1e2100000011
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1e2100000012"
down_revision: str | None = "b1e2100000011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("plugins") as batch_op:
        batch_op.add_column(
            sa.Column("loader", sa.String(length=32), nullable=True),
        )
        batch_op.add_column(
            sa.Column("mod_id", sa.String(length=128), nullable=True),
        )
        batch_op.add_column(
            sa.Column(
                "is_disabled_on_disk",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("plugins") as batch_op:
        batch_op.drop_column("is_disabled_on_disk")
        batch_op.drop_column("mod_id")
        batch_op.drop_column("loader")
