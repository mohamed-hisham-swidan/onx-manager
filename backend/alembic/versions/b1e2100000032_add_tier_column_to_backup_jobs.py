"""add tier column to backup_jobs (P7 two-tier backups)

Revision ID: b1e2100000032
Revises: b1e2100000031
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000032"
down_revision: str | None = "b1e2100000031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKUP_JOBS_TABLE = "backup_jobs"
BACKUP_JOBS_TIER_COLUMN = "tier"


def _existing_columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 1. backup_jobs: add tier discriminator (tier_1 / tier_2).
    if BACKUP_JOBS_TABLE in existing_tables:
        with op.batch_alter_table(BACKUP_JOBS_TABLE) as batch_op:
            batch_op.add_column(
                sa.Column(
                    BACKUP_JOBS_TIER_COLUMN,
                    sa.String(length=16),
                    nullable=True,
                    server_default="tier_1",
                )
            )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    if BACKUP_JOBS_TABLE in existing_tables:
        cols = _existing_columns(inspector, BACKUP_JOBS_TABLE)
        if BACKUP_JOBS_TIER_COLUMN in cols:
            with op.batch_alter_table(BACKUP_JOBS_TABLE) as batch_op:
                batch_op.drop_column(BACKUP_JOBS_TIER_COLUMN)
