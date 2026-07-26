"""add_server_type_to_servers

Revision ID: 5a50140d37df
Revises: 003
Create Date: 2026-07-24 15:55:56.359897
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5a50140d37df'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "servers",
        sa.Column("server_type", sa.String(32), nullable=False, server_default="vanilla"),
    )


def downgrade() -> None:
    op.drop_column("servers", "server_type")
