"""add updated_at column to alert_rules

Revision ID: a2b2c3d4e5f7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "a2b2c3d4e5f7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in inspect(conn).get_columns("alert_rules")}
    if "updated_at" not in existing:
        op.add_column(
            "alert_rules",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )


def downgrade() -> None:
    op.drop_column("alert_rules", "updated_at")
