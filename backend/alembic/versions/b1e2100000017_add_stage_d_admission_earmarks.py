"""add stage d admission earmarks and lease sentinel

Revision ID: b1e2100000017
Revises: b1e2100000016
Create Date: 2026-09-17
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000017"
down_revision: str | None = "b1e2100000016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _test_run_columns(inspector) -> set[str]:
    return {c["name"] for c in inspector.get_columns("server_test_runs")}


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    # 1. Reservation earmark columns on server_test_runs (nullable: pre-migration
    # rows carry NULL and fall back to recomputation per the Stage D spec).
    if "server_test_runs" in existing_tables:
        cols = _test_run_columns(inspector)
        if "reserved_ram_mb" not in cols:
            op.add_column(
                "server_test_runs",
                sa.Column("reserved_ram_mb", sa.Integer(), nullable=True),
            )
        if "reserved_cores" not in cols:
            op.add_column(
                "server_test_runs",
                sa.Column("reserved_cores", sa.Integer(), nullable=True),
            )

    # 2. Single-row cross-process admission mutex.
    if "server_admission_lease" not in existing_tables:
        op.create_table(
            "server_admission_lease",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("holder", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("id = 1", name="ck_admission_lease_singleton"),
        )
        op.execute(
            sa.text(
                "INSERT INTO server_admission_lease (id, holder, acquired_at) "
                "VALUES (1, '', :now)"
            ).bindparams(now=datetime.now(UTC))
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "server_admission_lease" in tables:
        op.drop_table("server_admission_lease")

    if "server_test_runs" in tables:
        cols = _test_run_columns(inspector)
        with op.batch_alter_table("server_test_runs") as batch_op:
            if "reserved_cores" in cols:
                batch_op.drop_column("reserved_cores")
            if "reserved_ram_mb" in cols:
                batch_op.drop_column("reserved_ram_mb")
