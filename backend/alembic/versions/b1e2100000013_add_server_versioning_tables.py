"""add server versioning tables and bot_verification_settings column

Revision ID: b1e2100000013
Revises: b1e2100000012
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1e2100000013"
down_revision: str | None = "b1e2100000012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. server_branches
    op.create_table(
        "server_branches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("server_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("head_commit_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("server_id", "name", name="uq_server_branch_name"),
    )

    # 2. server_world_snapshots
    op.create_table(
        "server_world_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("server_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 3. server_commits
    op.create_table(
        "server_commits",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("server_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("branch_id", sa.String(length=36), nullable=True, index=True),
        sa.Column("parent_commit_id", sa.String(length=36), nullable=True, index=True),
        sa.Column("author_id", sa.String(length=36), nullable=True),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("world_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 4. server_test_runs
    op.create_table(
        "server_test_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("server_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("commit_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("node_id", sa.String(length=64), nullable=False, server_default="local"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("ephemeral_port", sa.Integer(), nullable=True),
        sa.Column("log_output", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bot_count", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("placement_mode", sa.String(length=32), nullable=False, server_default="sidecar"),
        sa.Column("bot_tech", sa.String(length=32), nullable=False, server_default="auto"),
    )

    # 5. servers.bot_verification_settings column
    with op.batch_alter_table("servers") as batch_op:
        batch_op.add_column(
            sa.Column("bot_verification_settings", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("servers") as batch_op:
        batch_op.drop_column("bot_verification_settings")

    op.drop_table("server_test_runs")
    op.drop_table("server_commits")
    op.drop_table("server_world_snapshots")
    op.drop_table("server_branches")
