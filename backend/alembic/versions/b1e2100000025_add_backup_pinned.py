"""add pinned column to backup jobs

Revision ID: b1e2100000025
Revises: b1e2100000024
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000025"
down_revision: str | None = "b1e2100000024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backup_job_columns() -> set[str]:
    conn = op.get_bind()
    return {c["name"] for c in inspect(conn).get_columns("backup_jobs")}


def upgrade() -> None:
    if "pinned" not in _backup_job_columns():
        with op.batch_alter_table("backup_jobs") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "pinned",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )


def downgrade() -> None:
    if "pinned" in _backup_job_columns():
        with op.batch_alter_table("backup_jobs") as batch_op:
            batch_op.drop_column("pinned")
