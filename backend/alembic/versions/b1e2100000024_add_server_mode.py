"""add server mode column

Revision ID: b1e2100000024
Revises: b1e2100000023
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000024"
down_revision: str | None = "b1e2100000023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in inspect(conn).get_columns("servers")}
    if "mode" not in existing:
        with op.batch_alter_table("servers") as batch_op:
            batch_op.add_column(
                sa.Column("mode", sa.String(16), nullable=False, server_default="simple")
            )


def downgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in inspect(conn).get_columns("servers")}
    if "mode" in existing:
        with op.batch_alter_table("servers") as batch_op:
            batch_op.drop_column("mode")
