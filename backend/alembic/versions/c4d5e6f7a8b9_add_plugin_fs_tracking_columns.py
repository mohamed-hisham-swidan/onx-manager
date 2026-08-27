"""add_plugin_fs_tracking_columns

Revision ID: c4d5e6f7a8b9
Revises: 3a42d373bb05
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "3a42d373bb05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in inspect(conn).get_columns("plugins")}
    if "filename" not in existing:
        op.add_column("plugins", sa.Column("filename", sa.String(255), nullable=True))
    if "pending_deletion" not in existing:
        op.add_column(
            "plugins",
            sa.Column("pending_deletion", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "pending_deletion_requested_at" not in existing:
        op.add_column(
            "plugins",
            sa.Column(
                "pending_deletion_requested_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )


def downgrade() -> None:
    op.drop_column("plugins", "pending_deletion_requested_at")
    op.drop_column("plugins", "pending_deletion")
    op.drop_column("plugins", "filename")
