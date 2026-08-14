"""add exposure subsystem tables

Revision ID: b1e2100000001
Revises: a957791492a7
Create Date: 2026-08-13 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'b1e2100000001'
down_revision: str | None = 'a957791492a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'host_playit_agent',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('secret_ciphertext', sa.LargeBinary(), nullable=True),
        sa.Column('claim_code', sa.String(length=255), nullable=True),
        sa.Column('claim_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('process_status', sa.String(length=16), nullable=False),
        sa.Column('last_health_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('desired_agent_running', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table(
        'server_exposure',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('server_id', sa.String(length=36), nullable=False),
        sa.Column('method', sa.String(length=16), nullable=False),
        sa.Column('desired_state', sa.String(length=16), nullable=False),
        sa.Column('aggregate_status', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['server_id'], ['servers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        op.f('ix_server_exposure_server_id'), 'server_exposure', ['server_id'], unique=True
    )
    op.create_table(
        'server_exposure_target',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('exposure_id', sa.String(length=36), nullable=False),
        sa.Column('protocol', sa.String(length=8), nullable=False),
        sa.Column('service_type', sa.String(length=16), nullable=False),
        sa.Column('local_port', sa.Integer(), nullable=False),
        sa.Column('public_address', sa.String(length=512), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['exposure_id'], ['server_exposure.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'exposure_id', 'service_type', 'protocol', name='uq_exposure_target_service_protocol'
        )
    )
    op.create_index(
        op.f('ix_server_exposure_target_exposure_id'),
        'server_exposure_target',
        ['exposure_id'],
        unique=False,
    )
    op.create_table(
        'panel_exposure',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('method', sa.String(length=32), nullable=False),
        sa.Column('desired_state', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('public_address', sa.String(length=512), nullable=True),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table(
        'server_exposure_grants',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('server_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('can_manage', sa.Boolean(), nullable=False),
        sa.Column('can_view', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['server_id'], ['servers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('server_id', 'user_id', name='uq_exposure_grant_server_user')
    )
    op.create_index(
        op.f('ix_server_exposure_grants_server_id'),
        'server_exposure_grants',
        ['server_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_server_exposure_grants_user_id'),
        'server_exposure_grants',
        ['user_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_server_exposure_grants_user_id'), table_name='server_exposure_grants')
    op.drop_index(op.f('ix_server_exposure_grants_server_id'), table_name='server_exposure_grants')
    op.drop_table('server_exposure_grants')
    op.drop_table('panel_exposure')
    op.drop_index(
        op.f('ix_server_exposure_target_exposure_id'), table_name='server_exposure_target'
    )
    op.drop_table('server_exposure_target')
    op.drop_index(op.f('ix_server_exposure_server_id'), table_name='server_exposure')
    op.drop_table('server_exposure')
    op.drop_table('host_playit_agent')
