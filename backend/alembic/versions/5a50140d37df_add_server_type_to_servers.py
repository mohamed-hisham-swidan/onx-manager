"""add_server_type_to_servers

Revision ID: 5a50140d37df
Revises: 003
Create Date: 2026-07-24 15:55:56.359897
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "5a50140d37df"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in inspect(conn).get_columns("servers")}
    if "server_type" not in existing:
        op.add_column(
            "servers",
            sa.Column("server_type", sa.String(32), nullable=False, server_default="vanilla"),
        )


def downgrade() -> None:
    op.drop_column("servers", "server_type")
