"""add refresh journals and server repo leases

Revision ID: b1e2100000026
Revises: b1e2100000025
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000026"
down_revision: str | None = "b1e2100000025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_JOURNAL_INDEX = "ix_refresh_journals_server_active"


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "server_repo_leases" not in existing_tables:
        op.create_table(
            "server_repo_leases",
            sa.Column("server_id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("holder", sa.String(length=128), nullable=True),
            sa.Column(
                "fencing_token",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "previous_tree_retention",
                sa.String(length=32),
                nullable=False,
                server_default="until_health_gate",
            ),
            sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "refresh_journals" not in existing_tables:
        op.create_table(
            "refresh_journals",
            sa.Column("journal_id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("server_id", sa.String(length=36), nullable=False, index=True),
            sa.Column("export_id", sa.String(length=36), nullable=True),
            sa.Column("fencing_token", sa.BigInteger(), nullable=False),
            sa.Column("phase", sa.String(length=64), nullable=False, index=True),
            sa.Column(
                "terminal",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("previous_main_sha", sa.String(length=64), nullable=True),
            sa.Column("target_main_sha", sa.String(length=64), nullable=True),
            sa.Column("pre_upgrade_backup_id", sa.String(length=36), nullable=True),
            sa.Column("class_c_snapshot_id", sa.String(length=36), nullable=True),
            sa.Column("live_path", sa.Text(), nullable=False),
            sa.Column("staging_path", sa.Text(), nullable=False),
            sa.Column("previous_path", sa.Text(), nullable=True),
            sa.Column(
                "used_exchange",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "carried_entries_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "retention_policy",
                sa.String(length=32),
                nullable=False,
                server_default="until_health_gate",
            ),
            sa.Column(
                "previous_tree_retained",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("previous_tree_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            ACTIVE_JOURNAL_INDEX,
            "refresh_journals",
            ["server_id"],
            unique=True,
            sqlite_where=sa.text("terminal = 0"),
            postgresql_where=sa.text("terminal = false"),
        )
    else:
        existing_indexes = {
            index["name"] for index in inspector.get_indexes("refresh_journals")
        }
        if ACTIVE_JOURNAL_INDEX not in existing_indexes:
            op.create_index(
                ACTIVE_JOURNAL_INDEX,
                "refresh_journals",
                ["server_id"],
                unique=True,
                sqlite_where=sa.text("terminal = 0"),
                postgresql_where=sa.text("terminal = false"),
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "refresh_journals" in existing_tables:
        existing_indexes = {
            index["name"] for index in inspector.get_indexes("refresh_journals")
        }
        if ACTIVE_JOURNAL_INDEX in existing_indexes:
            op.drop_index(ACTIVE_JOURNAL_INDEX, table_name="refresh_journals")
        op.drop_table("refresh_journals")

    if "server_repo_leases" in existing_tables:
        op.drop_table("server_repo_leases")
