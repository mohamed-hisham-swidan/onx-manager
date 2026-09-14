"""add server activity logs table

Revision ID: b1e2100000014
Revises: b1e2100000013
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1e2100000014"
down_revision: str | None = "b1e2100000013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "server_activity_logs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("server_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("timestamp", sa.Float(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False, index=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False, server_default="system"),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_activity_server_timestamp",
        "server_activity_logs",
        ["server_id", "timestamp"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_activity_server_timestamp", table_name="server_activity_logs")
    op.drop_table("server_activity_logs")
