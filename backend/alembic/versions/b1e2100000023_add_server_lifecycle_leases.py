"""add server lifecycle leases table

Revision ID: b1e2100000023
Revises: b1e2100000022
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000023"
down_revision: str | None = "b1e2100000022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    if "server_lifecycle_leases" not in existing_tables:
        op.create_table(
            "server_lifecycle_leases",
            sa.Column("server_id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column("holder", sa.String(length=128), nullable=True),
            sa.Column("owner_token", sa.String(length=64), nullable=True),
            sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "server_lifecycle_leases" in tables:
        op.drop_table("server_lifecycle_leases")
