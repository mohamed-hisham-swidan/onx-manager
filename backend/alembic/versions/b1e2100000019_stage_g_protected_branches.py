"""add stage g protected branches columns

Revision ID: b1e2100000019
Revises: b1e2100000018
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000019"
down_revision: str | None = "b1e2100000018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _branch_columns(inspector) -> set[str]:
    return {c["name"] for c in inspector.get_columns("server_branches")}


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_cols = _branch_columns(inspector)

    with op.batch_alter_table("server_branches") as batch_op:
        if "is_protected" not in existing_cols:
            batch_op.add_column(
                sa.Column(
                    "is_protected",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )
        if "protection_policy" not in existing_cols:
            batch_op.add_column(
                sa.Column(
                    "protection_policy",
                    sa.JSON(),
                    nullable=True,
                )
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_cols = _branch_columns(inspector)

    with op.batch_alter_table("server_branches") as batch_op:
        if "protection_policy" in existing_cols:
            batch_op.drop_column("protection_policy")
        if "is_protected" in existing_cols:
            batch_op.drop_column("is_protected")
