"""Branch-scoped server exposure and pending settings auto-branch metadata.

Revision ID: b1e2100000034
Revises: b1e2100000033
Create Date: 2026-11-23 16:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000034"
down_revision: str | None = "b1e2100000033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPOSURE_TABLE = "server_exposure"
BRANCHES_TABLE = "server_branches"
UQ_EXPOSURE_SERVER_BRANCH = "uq_server_exposure_server_branch"
IX_EXPOSURE_SERVER_ID = "ix_server_exposure_server_id"
IX_EXPOSURE_SERVER_BRANCH = "ix_server_exposure_server_branch"


def _existing_columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def _existing_indexes(inspector, table: str) -> dict[str, dict]:
    return {str(ix["name"]): ix for ix in inspector.get_indexes(table) if ix.get("name")}


def _existing_uniques(inspector, table: str) -> set[str]:
    return {
        str(uc["name"]) for uc in inspector.get_unique_constraints(table) if uc.get("name")
    }


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())

    if EXPOSURE_TABLE in tables:
        cols = _existing_columns(inspector, EXPOSURE_TABLE)
        indexes = _existing_indexes(inspector, EXPOSURE_TABLE)
        uniques = _existing_uniques(inspector, EXPOSURE_TABLE)

        # Drop unique index on server_id if it enforces unique=True across branches
        old_idx = indexes.get(IX_EXPOSURE_SERVER_ID)
        if old_idx is not None and old_idx.get("unique"):
            op.drop_index(IX_EXPOSURE_SERVER_ID, table_name=EXPOSURE_TABLE)

        with op.batch_alter_table(EXPOSURE_TABLE) as batch_op:
            if "branch_name" not in cols:
                batch_op.add_column(
                    sa.Column(
                        "branch_name",
                        sa.String(length=64),
                        nullable=False,
                        server_default="main",
                    )
                )
            if "cloudflare_mode" not in cols:
                batch_op.add_column(
                    sa.Column("cloudflare_mode", sa.String(length=16), nullable=True)
                )
            if "subdomain_prefix" not in cols:
                batch_op.add_column(
                    sa.Column("subdomain_prefix", sa.String(length=63), nullable=True)
                )
            if "base_domain" not in cols:
                batch_op.add_column(
                    sa.Column("base_domain", sa.String(length=255), nullable=True)
                )
            if "srv_record_enabled" not in cols:
                batch_op.add_column(
                    sa.Column(
                        "srv_record_enabled",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("0"),
                    )
                )
            if "ephemeral" not in cols:
                batch_op.add_column(
                    sa.Column(
                        "ephemeral",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("0"),
                    )
                )
            if UQ_EXPOSURE_SERVER_BRANCH not in uniques:
                batch_op.create_unique_constraint(
                    UQ_EXPOSURE_SERVER_BRANCH, ["server_id", "branch_name"]
                )

        inspector = inspect(connection)
        indexes = _existing_indexes(inspector, EXPOSURE_TABLE)
        if IX_EXPOSURE_SERVER_ID not in indexes:
            op.create_index(IX_EXPOSURE_SERVER_ID, EXPOSURE_TABLE, ["server_id"], unique=False)
        if IX_EXPOSURE_SERVER_BRANCH not in indexes:
            op.create_index(
                IX_EXPOSURE_SERVER_BRANCH,
                EXPOSURE_TABLE,
                ["server_id", "branch_name"],
                unique=False,
            )

    inspector = inspect(connection)
    if BRANCHES_TABLE in tables:
        bcols = _existing_columns(inspector, BRANCHES_TABLE)
        with op.batch_alter_table(BRANCHES_TABLE) as batch_op:
            if "pending_merge_on_restart" not in bcols:
                batch_op.add_column(
                    sa.Column(
                        "pending_merge_on_restart",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("0"),
                    )
                )
            if "pending_merge_status" not in bcols:
                batch_op.add_column(
                    sa.Column("pending_merge_status", sa.String(length=32), nullable=True)
                )
            if "pending_merge_error" not in bcols:
                batch_op.add_column(sa.Column("pending_merge_error", sa.Text(), nullable=True))


def downgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())

    if BRANCHES_TABLE in tables:
        bcols = _existing_columns(inspector, BRANCHES_TABLE)
        with op.batch_alter_table(BRANCHES_TABLE) as batch_op:
            for col_name in (
                "pending_merge_error",
                "pending_merge_status",
                "pending_merge_on_restart",
            ):
                if col_name in bcols:
                    batch_op.drop_column(col_name)

    inspector = inspect(connection)
    if EXPOSURE_TABLE in tables:
        cols = _existing_columns(inspector, EXPOSURE_TABLE)
        indexes = _existing_indexes(inspector, EXPOSURE_TABLE)
        uniques = _existing_uniques(inspector, EXPOSURE_TABLE)
        if IX_EXPOSURE_SERVER_BRANCH in indexes:
            op.drop_index(IX_EXPOSURE_SERVER_BRANCH, table_name=EXPOSURE_TABLE)
        if IX_EXPOSURE_SERVER_ID in indexes:
            op.drop_index(IX_EXPOSURE_SERVER_ID, table_name=EXPOSURE_TABLE)
        with op.batch_alter_table(EXPOSURE_TABLE) as batch_op:
            if UQ_EXPOSURE_SERVER_BRANCH in uniques:
                batch_op.drop_constraint(UQ_EXPOSURE_SERVER_BRANCH, type_="unique")
            for col_name in (
                "ephemeral",
                "srv_record_enabled",
                "base_domain",
                "subdomain_prefix",
                "cloudflare_mode",
                "branch_name",
            ):
                if col_name in cols:
                    batch_op.drop_column(col_name)
        op.create_index(IX_EXPOSURE_SERVER_ID, EXPOSURE_TABLE, ["server_id"], unique=True)
