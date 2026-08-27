"""add_external_id_to_servers

Revision ID: 902b076bfa36
Revises: fcc7545db19e
Create Date: 2026-07-25 10:41:01.584117
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "902b076bfa36"
down_revision: str | None = "fcc7545db19e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in inspect(conn).get_columns("servers")}
    if "external_id" not in existing:
        op.add_column("servers", sa.Column("external_id", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("servers", "external_id")
