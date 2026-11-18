"""add p4 branches ports data templates

Revision ID: b1e2100000029
Revises: b1e2100000028
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000029"
down_revision: str | None = "b1e2100000028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SERVER_DATA_TEMPLATES_TABLE = "server_data_templates"
SERVER_DATA_TEMPLATES_INDEX = "ix_server_data_templates_server_id"
SERVER_DATA_TEMPLATES_UNIQUE = "uq_server_data_template_name"

RUNTIMES_INDEX = "ix_server_runtimes_server_branch"
ACTIVITY_INDEX = "ix_activity_server_branch_timestamp"


def _existing_columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def _add_column_if_missing(inspector, table: str, column: sa.Column) -> None:
    if column.name not in _existing_columns(inspector, table):
        op.add_column(table, column)


def _index_exists(inspector, table: str, index_name: str) -> bool:
    return index_name in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 1. server_data_templates
    if SERVER_DATA_TEMPLATES_TABLE not in existing_tables:
        op.create_table(
            SERVER_DATA_TEMPLATES_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column(
                "server_id",
                sa.String(length=36),
                sa.ForeignKey("servers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column(
                "description",
                sa.String(length=500),
                nullable=False,
                server_default="",
            ),
            sa.Column("source_branch_name", sa.String(length=64), nullable=True),
            sa.Column("source_commit_sha", sa.String(length=64), nullable=True),
            sa.Column("storage_path", sa.String(length=512), nullable=False),
            sa.Column(
                "file_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "total_bytes",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="ready",
            ),
            sa.Column("operation_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "server_id", "name", name=SERVER_DATA_TEMPLATES_UNIQUE
            ),
        )
        op.create_index(
            SERVER_DATA_TEMPLATES_INDEX,
            SERVER_DATA_TEMPLATES_TABLE,
            ["server_id"],
        )

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 2. server_branches
    if "server_branches" in existing_tables:
        _add_column_if_missing(
            inspector, "server_branches", sa.Column("port_set_json", sa.JSON(), nullable=True)
        )
        _add_column_if_missing(
            inspector,
            "server_branches",
            sa.Column(
                "runtime_status",
                sa.String(length=32),
                nullable=False,
                server_default="stopped",
            ),
        )
        _add_column_if_missing(
            inspector,
            "server_branches",
            sa.Column("active_runtime_id", sa.String(length=64), nullable=True),
        )
        _add_column_if_missing(
            inspector,
            "server_branches",
            sa.Column("active_commit_sha", sa.String(length=64), nullable=True),
        )
        _add_column_if_missing(
            inspector,
            "server_branches",
            sa.Column("active_data_template_id", sa.String(length=36), nullable=True),
        )

    # 3. server_runtimes
    if "server_runtimes" in existing_tables:
        inspector = inspect(connection)
        _add_column_if_missing(
            inspector,
            "server_runtimes",
            sa.Column("branch_name", sa.String(length=64), nullable=True),
        )
        _add_column_if_missing(
            inspector,
            "server_runtimes",
            sa.Column("data_template_id", sa.String(length=36), nullable=True),
        )
        _add_column_if_missing(
            inspector, "server_runtimes", sa.Column("port_set_json", sa.JSON(), nullable=True)
        )
        _add_column_if_missing(
            inspector,
            "server_runtimes",
            sa.Column(
                "allow_public_test_join",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
        _add_column_if_missing(
            inspector,
            "server_runtimes",
            sa.Column("export_path", sa.String(length=512), nullable=True),
        )
        inspector = inspect(connection)
        if not _index_exists(inspector, "server_runtimes", RUNTIMES_INDEX):
            op.create_index(RUNTIMES_INDEX, "server_runtimes", ["server_id", "branch_name"])

    # 4. server_test_runs
    if "server_test_runs" in existing_tables:
        inspector = inspect(connection)
        _add_column_if_missing(
            inspector,
            "server_test_runs",
            sa.Column("branch_name", sa.String(length=64), nullable=True),
        )
        _add_column_if_missing(
            inspector,
            "server_test_runs",
            sa.Column("data_template_id", sa.String(length=36), nullable=True),
        )
        _add_column_if_missing(
            inspector, "server_test_runs", sa.Column("port_set_json", sa.JSON(), nullable=True)
        )

    # 5. servers
    if "servers" in existing_tables:
        inspector = inspect(connection)
        _add_column_if_missing(
            inspector,
            "servers",
            sa.Column(
                "rcon_save_off_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
        _add_column_if_missing(
            inspector,
            "servers",
            sa.Column(
                "max_concurrent_branch_runs",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )

    # 6. server_activity_logs
    if "server_activity_logs" in existing_tables:
        inspector = inspect(connection)
        _add_column_if_missing(
            inspector,
            "server_activity_logs",
            sa.Column("branch_name", sa.String(length=64), nullable=True),
        )
        inspector = inspect(connection)
        if not _index_exists(inspector, "server_activity_logs", ACTIVITY_INDEX):
            op.create_index(
                ACTIVITY_INDEX,
                "server_activity_logs",
                ["server_id", "branch_name", "timestamp"],
            )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)

    # Drop index on activity
    if "server_activity_logs" in set(inspector.get_table_names()):
        inspector = inspect(connection)
        if _index_exists(inspector, "server_activity_logs", ACTIVITY_INDEX):
            op.drop_index(ACTIVITY_INDEX, table_name="server_activity_logs")
        cols = _existing_columns(inspector, "server_activity_logs")
        if "branch_name" in cols:
            with op.batch_alter_table("server_activity_logs") as batch_op:
                batch_op.drop_column("branch_name")

    # servers columns
    if "servers" in set(inspector.get_table_names()):
        inspector = inspect(connection)
        cols = _existing_columns(inspector, "servers")
        with op.batch_alter_table("servers") as batch_op:
            if "rcon_save_off_active" in cols:
                batch_op.drop_column("rcon_save_off_active")
            if "max_concurrent_branch_runs" in cols:
                batch_op.drop_column("max_concurrent_branch_runs")

    # server_test_runs columns
    if "server_test_runs" in set(inspector.get_table_names()):
        inspector = inspect(connection)
        cols = _existing_columns(inspector, "server_test_runs")
        with op.batch_alter_table("server_test_runs") as batch_op:
            for name in ("branch_name", "data_template_id", "port_set_json"):
                if name in cols:
                    batch_op.drop_column(name)

    # server_runtimes columns + index
    if "server_runtimes" in set(inspector.get_table_names()):
        inspector = inspect(connection)
        if _index_exists(inspector, "server_runtimes", RUNTIMES_INDEX):
            op.drop_index(RUNTIMES_INDEX, table_name="server_runtimes")
        cols = _existing_columns(inspector, "server_runtimes")
        with op.batch_alter_table("server_runtimes") as batch_op:
            for name in (
                "branch_name",
                "data_template_id",
                "port_set_json",
                "allow_public_test_join",
                "export_path",
            ):
                if name in cols:
                    batch_op.drop_column(name)

    # server_branches columns
    if "server_branches" in set(inspector.get_table_names()):
        inspector = inspect(connection)
        cols = _existing_columns(inspector, "server_branches")
        with op.batch_alter_table("server_branches") as batch_op:
            for name in (
                "port_set_json",
                "runtime_status",
                "active_runtime_id",
                "active_commit_sha",
                "active_data_template_id",
            ):
                if name in cols:
                    batch_op.drop_column(name)

    # drop server_data_templates
    if SERVER_DATA_TEMPLATES_TABLE in set(inspector.get_table_names()):
        inspector = inspect(connection)
        if _index_exists(inspector, SERVER_DATA_TEMPLATES_TABLE, SERVER_DATA_TEMPLATES_INDEX):
            op.drop_index(SERVER_DATA_TEMPLATES_INDEX, table_name=SERVER_DATA_TEMPLATES_TABLE)
        op.drop_table(SERVER_DATA_TEMPLATES_TABLE)
