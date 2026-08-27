"""Add Batch-09 tables: task_queue, cron_jobs, metric_points, alert_rules + crypto chain cols

Revision ID: 002
Revises: 001
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_queue",
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("delay_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "cron_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("cron_expression", sa.String(64), nullable=False),
        sa.Column("task_name", sa.String(128), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "metric_points",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("server_id", sa.String(36), nullable=False),
        sa.Column("tps", sa.Float(), nullable=False),
        sa.Column("players", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ram_used_mb", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cpu_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_metric_points_server_id", "metric_points", ["server_id"])

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("server_id", sa.String(36), nullable=False),
        sa.Column("metric_name", sa.String(64), nullable=False),
        sa.Column("condition", sa.String(8), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="warning"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alert_rules_server_id", "alert_rules", ["server_id"])

    op.add_column("event_store", sa.Column("previous_hash", sa.String(64), nullable=True))
    op.add_column(
        "event_store", sa.Column("hash", sa.String(64), nullable=False, server_default="")
    )

    op.add_column(
        "dead_letter_events",
        sa.Column("replay_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "dead_letter_events", sa.Column("last_replay_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "dead_letter_events",
        sa.Column("resolved", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("dead_letter_events", "resolved")
    op.drop_column("dead_letter_events", "last_replay_at")
    op.drop_column("dead_letter_events", "replay_count")
    op.drop_column("event_store", "hash")
    op.drop_column("event_store", "previous_hash")
    op.drop_index("ix_alert_rules_server_id", "alert_rules")
    op.drop_table("alert_rules")
    op.drop_index("ix_metric_points_server_id", "metric_points")
    op.drop_table("metric_points")
    op.drop_table("cron_jobs")
    op.drop_table("task_queue")
