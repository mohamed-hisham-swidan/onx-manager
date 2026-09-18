"""add stage f test platform tables and columns

Revision ID: b1e2100000018
Revises: b1e2100000017
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000018"
down_revision: str | None = "b1e2100000017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _test_run_columns(inspector) -> set[str]:
    return {c["name"] for c in inspector.get_columns("server_test_runs")}


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    # 1. server_runtimes table
    if "server_runtimes" not in existing_tables:
        op.create_table(
            "server_runtimes",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column(
                "server_id",
                sa.String(length=36),
                sa.ForeignKey("servers.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "commit_id",
                sa.String(length=64),
                sa.ForeignKey("server_commits.id"),
                nullable=False,
            ),
            sa.Column("materialization_id", sa.String(length=64), nullable=True),
            sa.Column(
                "provider_type",
                sa.String(length=32),
                nullable=False,
                server_default="docker",
            ),
            sa.Column("container_id", sa.String(length=255), nullable=True),
            sa.Column("pid", sa.Integer(), nullable=True),
            sa.Column("port", sa.Integer(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="starting",
            ),
            sa.Column("exit_code", sa.Integer(), nullable=True),
            sa.Column(
                "oom_killed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    # 2. server_test_definitions table
    if "server_test_definitions" not in existing_tables:
        op.create_table(
            "server_test_definitions",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column(
                "server_id",
                sa.String(length=36),
                sa.ForeignKey("servers.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column(
                "description",
                sa.String(length=500),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "server_type",
                sa.String(length=32),
                nullable=False,
                server_default="vanilla",
            ),
            sa.Column(
                "bot_technology",
                sa.String(length=32),
                nullable=False,
                server_default="mineflayer",
            ),
            sa.Column("bot_count", sa.Integer(), nullable=False, server_default="5"),
            sa.Column(
                "duration_seconds",
                sa.Integer(),
                nullable=False,
                server_default="60",
            ),
            sa.Column(
                "join_stagger_seconds",
                sa.Float(),
                nullable=False,
                server_default="1.0",
            ),
            sa.Column(
                "connect_grace_seconds",
                sa.Integer(),
                nullable=False,
                server_default="20",
            ),
            sa.Column(
                "placement_mode",
                sa.String(length=32),
                nullable=False,
                server_default="sidecar",
            ),
            sa.Column("assertion_rules", sa.JSON(), nullable=False),
            sa.Column(
                "timeout_seconds",
                sa.Integer(),
                nullable=False,
                server_default="300",
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    # 3. Add columns to server_test_runs
    if "server_test_runs" in existing_tables:
        cols = _test_run_columns(inspector)
        with op.batch_alter_table("server_test_runs") as batch_op:
            if "runtime_id" not in cols:
                batch_op.add_column(
                    sa.Column(
                        "runtime_id",
                        sa.String(length=64),
                        sa.ForeignKey(
                            "server_runtimes.id",
                            name="fk_server_test_runs_runtime_id",
                            ondelete="SET NULL",
                        ),
                        nullable=True,
                    )
                )
            if "test_definition_id" not in cols:
                batch_op.add_column(
                    sa.Column(
                        "test_definition_id",
                        sa.String(length=64),
                        sa.ForeignKey(
                            "server_test_definitions.id",
                            name="fk_server_test_runs_test_definition_id",
                            ondelete="SET NULL",
                        ),
                        nullable=True,
                    )
                )
            if "evidence_bundle" not in cols:
                batch_op.add_column(
                    sa.Column("evidence_bundle", sa.JSON(), nullable=True)
                )
            if "artifacts_purged" not in cols:
                batch_op.add_column(
                    sa.Column(
                        "artifacts_purged",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.false(),
                    )
                )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    if "server_test_runs" in existing_tables:
        cols = _test_run_columns(inspector)
        with op.batch_alter_table("server_test_runs") as batch_op:
            for col_name in ("artifacts_purged", "evidence_bundle", "test_definition_id", "runtime_id"):
                if col_name in cols:
                    batch_op.drop_column(col_name)

    if "server_test_definitions" in existing_tables:
        op.drop_table("server_test_definitions")

    if "server_runtimes" in existing_tables:
        op.drop_table("server_runtimes")
