"""add operation_id to server_test_runs

Revision ID: b1e2100000022
Revises: b1e2100000021
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000022"
down_revision: str | None = "b1e2100000021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _test_run_columns(inspector) -> set[str]:
    return {c["name"] for c in inspector.get_columns("server_test_runs")}


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    if "server_test_runs" in existing_tables:
        cols = _test_run_columns(inspector)
        with op.batch_alter_table("server_test_runs") as batch_op:
            if "operation_id" not in cols:
                batch_op.add_column(
                    sa.Column(
                        "operation_id",
                        sa.String(length=36),
                        nullable=True,
                    )
                )
                batch_op.create_index(
                    "ix_server_test_runs_operation_id",
                    ["operation_id"],
                    unique=False,
                )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    if "server_test_runs" in existing_tables:
        cols = _test_run_columns(inspector)
        with op.batch_alter_table("server_test_runs") as batch_op:
            batch_op.drop_index("ix_server_test_runs_operation_id")
            if "operation_id" in cols:
                batch_op.drop_column("operation_id")
