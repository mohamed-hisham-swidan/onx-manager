"""add stage b versioning tables and branch status

Revision ID: b1e2100000015
Revises: b1e2100000014
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000015"
down_revision: str | None = "b1e2100000014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    # 1. Add status column to server_branches
    if "server_branches" in existing_tables:
        existing_branch_cols = {c["name"] for c in inspector.get_columns("server_branches")}
        if "status" not in existing_branch_cols:
            with op.batch_alter_table("server_branches") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "status",
                        sa.String(length=32),
                        nullable=False,
                        server_default="created",
                    ),
                )

        # Backfill active branches having a head_commit_id
        op.execute(
            "UPDATE server_branches SET status = 'active' "
            "WHERE head_commit_id IS NOT NULL AND head_commit_id != ''"
        )

    # 2. server_tags
    if "server_tags" not in existing_tables:
        op.create_table(
            "server_tags",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("server_id", sa.String(length=36), nullable=False, index=True),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("commit_id", sa.String(length=36), nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("server_id", "name", name="uq_server_tag_name"),
        )

    # 3. server_commit_parents
    if "server_commit_parents" not in existing_tables:
        op.create_table(
            "server_commit_parents",
            sa.Column("commit_id", sa.String(length=36), primary_key=True, index=True),
            sa.Column("parent_commit_id", sa.String(length=36), primary_key=True, index=True),
            sa.Column("parent_index", sa.Integer(), nullable=False, server_default="0"),
            sa.UniqueConstraint("commit_id", "parent_index", name="uq_commit_parent_index"),
        )

    # Backfill parents for existing single-parent commits
    if "server_commits" in existing_tables:
        op.execute(
            "INSERT OR IGNORE INTO server_commit_parents "
            "(commit_id, parent_commit_id, parent_index) "
            "SELECT id, parent_commit_id, 0 FROM server_commits "
            "WHERE parent_commit_id IS NOT NULL AND parent_commit_id != ''"
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "server_commit_parents" in tables:
        op.drop_table("server_commit_parents")
    if "server_tags" in tables:
        op.drop_table("server_tags")

    if "server_branches" in tables:
        existing_branch_cols = {c["name"] for c in inspector.get_columns("server_branches")}
        if "status" in existing_branch_cols:
            with op.batch_alter_table("server_branches") as batch_op:
                batch_op.drop_column("status")

