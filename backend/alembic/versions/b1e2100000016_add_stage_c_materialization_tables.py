"""add stage c materialization and import review tables

Revision ID: b1e2100000016
Revises: b1e2100000015
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000016"
down_revision: str | None = "b1e2100000015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    # 1. server_materializations
    if "server_materializations" not in existing_tables:
        op.create_table(
            "server_materializations",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("server_id", sa.String(length=36), nullable=False, index=True),
            sa.Column("commit_id", sa.String(length=36), nullable=False, index=True),
            sa.Column("root_path", sa.String(length=512), nullable=False),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "mode",
                sa.String(length=32),
                nullable=False,
                server_default="readonly",
            ),
            sa.Column(
                "revision",
                sa.String(length=255),
                nullable=False,
                server_default="",
            ),
            sa.Column("path_classification", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    # 2. server_import_reviews
    if "server_import_reviews" not in existing_tables:
        op.create_table(
            "server_import_reviews",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("server_id", sa.String(length=36), nullable=False, index=True),
            sa.Column("commit_id", sa.String(length=36), nullable=False, index=True),
            sa.Column("parent_commit_id", sa.String(length=36), nullable=True, index=True),
            sa.Column(
                "branch_name",
                sa.String(length=64),
                nullable=False,
                server_default="main",
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("changes", sa.JSON(), nullable=False),
            sa.Column("revert_commit_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "server_import_reviews" in tables:
        op.drop_table("server_import_reviews")
    if "server_materializations" in tables:
        op.drop_table("server_materializations")
