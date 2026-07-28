"""add health module tables (health_status, health_timeline, health_evidence, health_diagnostics)

Revision ID: 876be46160d4
Revises: 876be46160d3
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "876be46160d4"
down_revision: Union[str, None] = "876be46160d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "health_status",
        sa.Column("server_id", sa.String(36), primary_key=True),
        sa.Column("classification", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("previous_classification", sa.String(16), nullable=True),
        sa.Column("contributing_factors", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("trend", sa.String(16), nullable=False, server_default="stable"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "health_timeline",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.String(36), nullable=False, index=True),
        sa.Column("previous_status", sa.String(16), nullable=True),
        sa.Column("new_status", sa.String(16), nullable=False),
        sa.Column("contributing_factors", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("entry_timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "health_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("server_id", sa.String(36), nullable=False, index=True),
        sa.Column("latest_log_tail", sa.Text(), nullable=True),
        sa.Column("crash_reports", sa.Text(), nullable=True),
        sa.Column("provider_diagnostics", sa.Text(), nullable=True),
        sa.Column("system_snapshot", sa.Text(), nullable=True),
        sa.Column("collection_errors", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "health_diagnostics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("server_id", sa.String(36), nullable=False, index=True),
        sa.Column("evidence_id", sa.String(36), nullable=True),
        sa.Column("failure_code", sa.String(48), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("health_diagnostics")
    op.drop_table("health_evidence")
    op.drop_table("health_timeline")
    op.drop_table("health_status")
