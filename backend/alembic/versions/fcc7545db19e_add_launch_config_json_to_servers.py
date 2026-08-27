"""add launch_config_json column to servers

Revision ID: fcc7545db19e
Revises: ff9c2b3a8e4d
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "fcc7545db19e"
down_revision: str | None = "ff9c2b3a8e4d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in inspect(conn).get_columns("servers")}
    if "launch_config_json" not in existing:
        op.add_column("servers", sa.Column("launch_config_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("servers", "launch_config_json")
