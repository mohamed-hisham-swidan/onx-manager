"""Add icon_url to plugins

Revision ID: 989743c08820
Revises: 784b5ba72077
Create Date: 2026-08-09 22:47:13.650491
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "989743c08820"
down_revision: str | None = "784b5ba72077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plugins", sa.Column("icon_url", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("plugins", "icon_url")
