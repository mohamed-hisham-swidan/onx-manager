"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "feature_flags",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("enabled", sa.Boolean(), default=False, nullable=False),
        sa.Column("percentage", sa.Integer(), default=0, nullable=False),
        sa.Column("description", sa.Text(), default="", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "circuit_breaker_states",
        sa.Column("name", sa.String(128), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("failure_count", sa.Integer(), default=0, nullable=False),
        sa.Column("last_failure_time", sa.Float(), default=0.0, nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "saga_instances",
        sa.Column("saga_id", sa.String(36), primary_key=True),
        sa.Column("saga_type", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_step", sa.Integer(), default=0, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.Float(), default=0.0, nullable=False),
        sa.Column("timeout_seconds", sa.Float(), default=300.0, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "saga_steps",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column(
            "saga_id",
            sa.String(36),
            sa.ForeignKey("saga_instances.saga_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )

    op.create_table(
        "event_store",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("correlation_id", sa.String(36), default="", nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), default=1, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "dead_letter_events",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "feature_flag_overrides",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column(
            "flag_key",
            sa.String(128),
            sa.ForeignKey("feature_flags.key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("feature_flag_overrides")
    op.drop_table("dead_letter_events")
    op.drop_table("event_store")
    op.drop_table("saga_steps")
    op.drop_table("saga_instances")
    op.drop_table("circuit_breaker_states")
    op.drop_table("feature_flags")
    op.drop_table("idempotency_keys")
