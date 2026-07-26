"""add launch_config_json column to servers

Revision ID: fcc7545db19e
Revises: ff9c2b3a8e4d
Create Date: 2026-07-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "fcc7545db19e"
down_revision: Union[str, None] = "ff9c2b3a8e4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("launch_config_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("servers", "launch_config_json")
