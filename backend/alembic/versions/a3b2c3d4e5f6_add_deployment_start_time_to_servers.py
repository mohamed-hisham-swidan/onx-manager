"""add deployment_start_time column to servers

Revision ID: a3b2c3d4e5f6
Revises: a2b2c3d4e5f7
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "a3b2c3d4e5f6"
down_revision: Union[str, None] = "a2b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in inspect(conn).get_columns("servers")}
    if "deployment_start_time" not in existing:
        op.add_column("servers", sa.Column("deployment_start_time", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("servers", "deployment_start_time")
