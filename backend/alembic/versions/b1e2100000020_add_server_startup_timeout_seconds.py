"""add server startup timeout seconds column

Revision ID: b1e2100000020
Revises: b1e2100000019
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000020"
down_revision: str | None = "b1e2100000019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _server_columns(inspector) -> set[str]:
    return {c["name"] for c in inspector.get_columns("servers")}


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_cols = _server_columns(inspector)

    with op.batch_alter_table("servers") as batch_op:
        if "startup_timeout_seconds" not in existing_cols:
            batch_op.add_column(
                sa.Column(
                    "startup_timeout_seconds",
                    sa.Integer(),
                    nullable=True,
                )
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_cols = _server_columns(inspector)

    with op.batch_alter_table("servers") as batch_op:
        if "startup_timeout_seconds" in existing_cols:
            batch_op.drop_column("startup_timeout_seconds")
