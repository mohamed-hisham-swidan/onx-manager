"""add pending_restores table

Revision ID: b5c6d7e8f9a0
Revises: a3b2c3d4e5f6
Create Date: 2026-08-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, None] = "a3b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    """Return True if the table already exists in the current database."""
    conn = op.get_bind()
    inspector = inspect(conn)
    return name in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists("pending_restores"):
        op.create_table(
            "pending_restores",
            sa.Column("server_id", sa.String(36), primary_key=True),
            sa.Column("backup_id", sa.String(36), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    if _table_exists("pending_restores"):
        op.drop_table("pending_restores")
