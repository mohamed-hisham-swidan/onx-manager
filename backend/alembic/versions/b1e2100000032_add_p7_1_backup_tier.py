"""Add tier column and server_tier index to backup_jobs for P7-1 two-tier backups.

Revision ID: b1e2100000032
Revises: b1e2100000031
Create Date: 2026-11-20 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b1e2100000032"
down_revision = "b1e2100000031"
branch_labels = None
depends_on = None

BACKUP_JOBS_TABLE = "backup_jobs"
BACKUP_JOBS_TIER_COLUMN = "tier"
BACKUP_JOBS_SERVER_TIER_INDEX = "ix_backup_jobs_server_tier"


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def _existing_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {str(idx["name"]) for idx in inspector.get_indexes(table_name) if idx.get("name")}


def upgrade() -> None:
    cols = _existing_columns(BACKUP_JOBS_TABLE)
    if cols and BACKUP_JOBS_TIER_COLUMN not in cols:
        with op.batch_alter_table(BACKUP_JOBS_TABLE) as batch_op:
            batch_op.add_column(
                sa.Column(
                    BACKUP_JOBS_TIER_COLUMN,
                    sa.String(length=16),
                    nullable=False,
                    server_default=sa.text("'tier_1'"),
                )
            )
    indexes = _existing_indexes(BACKUP_JOBS_TABLE)
    if BACKUP_JOBS_SERVER_TIER_INDEX not in indexes:
        op.create_index(
            BACKUP_JOBS_SERVER_TIER_INDEX,
            BACKUP_JOBS_TABLE,
            ["server_id", BACKUP_JOBS_TIER_COLUMN],
            unique=False,
        )


def downgrade() -> None:
    indexes = _existing_indexes(BACKUP_JOBS_TABLE)
    if BACKUP_JOBS_SERVER_TIER_INDEX in indexes:
        op.drop_index(BACKUP_JOBS_SERVER_TIER_INDEX, table_name=BACKUP_JOBS_TABLE)
    cols = _existing_columns(BACKUP_JOBS_TABLE)
    if BACKUP_JOBS_TIER_COLUMN in cols:
        with op.batch_alter_table(BACKUP_JOBS_TABLE) as batch_op:
            batch_op.drop_column(BACKUP_JOBS_TIER_COLUMN)
