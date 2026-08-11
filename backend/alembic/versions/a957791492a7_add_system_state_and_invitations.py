"""add_system_state_and_invitations

Revision ID: a957791492a7
Revises: 5e2962848581
Create Date: 2026-08-11 16:07:01.691927
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a957791492a7'
down_revision: Union[str, None] = '5e2962848581'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'system_state',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('initialized', sa.Boolean(), nullable=False),
        sa.Column('access_mode', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table(
        'invitations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('token_hash', sa.String(length=128), nullable=False),
        sa.Column('token_prefix', sa.String(length=16), nullable=False),
        sa.Column('creator_id', sa.String(length=36), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('global_role', sa.String(length=32), nullable=False),
        sa.Column('server_id', sa.String(length=36), nullable=True),
        sa.Column('server_role', sa.String(length=32), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('max_uses', sa.Integer(), nullable=False),
        sa.Column('use_count', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.CheckConstraint('use_count <= max_uses', name='ck_invitation_use_count'),
        sa.ForeignKeyConstraint(['creator_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['server_id'], ['servers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invitations_email'), 'invitations', ['email'], unique=False)
    op.create_index(op.f('ix_invitations_token_hash'), 'invitations', ['token_hash'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_invitations_token_hash'), table_name='invitations')
    op.drop_index(op.f('ix_invitations_email'), table_name='invitations')
    op.drop_table('invitations')
    op.drop_table('system_state')

