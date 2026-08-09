"""Add icon_url to plugins

Revision ID: 989743c08820
Revises: 784b5ba72077
Create Date: 2026-08-09 22:47:13.650491
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '989743c08820'
down_revision: Union[str, None] = '784b5ba72077'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('plugins', sa.Column('icon_url', sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column('plugins', 'icon_url')
