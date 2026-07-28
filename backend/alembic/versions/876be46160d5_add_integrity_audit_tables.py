"""add integrity_audit and integrity_baseline tables

Revision ID: 876be46160d5
Revises: 876be46160d4
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "876be46160d5"
down_revision: Union[str, None] = "876be46160d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integrity_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.String(36), nullable=False, index=True),
        sa.Column("overall_status", sa.String(16), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False, server_default="full"),
        sa.Column("total_checks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_checks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_checks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "integrity_baseline",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("server_id", sa.String(36), nullable=False, index=True),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("file_name", sa.String(256), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("hash_algorithm", sa.String(16), nullable=False, server_default="sha256"),
        sa.Column("baseline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("integrity_baseline")
    op.drop_table("integrity_audit")
