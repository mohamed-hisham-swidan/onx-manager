"""stage a operations tables

Revision ID: b1e2100000021
Revises: b1e2100000020
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000021"
down_revision: str | None = "b1e2100000020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    if "operations" not in existing_tables:
        op.create_table(
            "operations",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("type", sa.String(length=64), nullable=False, index=True),
            sa.Column("target_type", sa.String(length=32), nullable=False),
            sa.Column("target_id", sa.String(length=36), nullable=True),
            sa.Column("actor_id", sa.String(length=36), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="QUEUED",
                index=True,
            ),
            sa.Column("idempotency_key", sa.String(length=64), nullable=True),
            sa.Column("current_step_id", sa.String(length=64), nullable=True),
            sa.Column("last_event_seq", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failure_code", sa.String(length=64), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "cancellation_requested",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="600"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
                index=True,
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.UniqueConstraint(
                "target_type",
                "target_id",
                "idempotency_key",
                name="uq_operations_target_idempotency",
            ),
        )
        op.create_index("idx_operations_target", "operations", ["target_type", "target_id"])

    if "operation_steps" not in existing_tables:
        op.create_table(
            "operation_steps",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "operation_id",
                sa.String(length=36),
                sa.ForeignKey("operations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("step_id", sa.String(length=64), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="PENDING",
                index=True,
            ),
            sa.Column("progress", sa.Float(), nullable=True),
            sa.Column("elapsed_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("message_key", sa.String(length=128), nullable=True),
            sa.Column("safe_to_retry", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("context_json", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("operation_id", "sequence", name="uq_operation_step_sequence"),
            sa.UniqueConstraint("operation_id", "step_id", name="uq_operation_step_id"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    if "operation_steps" in existing_tables:
        op.drop_table("operation_steps")

    if "operations" in existing_tables:
        op.drop_index("idx_operations_target", table_name="operations")
        op.drop_table("operations")
