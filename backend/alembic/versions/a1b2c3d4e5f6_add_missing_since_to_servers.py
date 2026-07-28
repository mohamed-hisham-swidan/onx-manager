"""add missing_since column to servers

Revision ID: a1b2c3d4e5f6
Revises: 876be46160d4
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "876be46160d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in inspect(conn).get_columns("servers")}
    if "missing_since" not in existing:
        op.add_column("servers", sa.Column("missing_since", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("servers", "missing_since")
