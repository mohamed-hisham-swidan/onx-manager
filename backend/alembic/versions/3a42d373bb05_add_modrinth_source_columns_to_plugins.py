"""add_modrinth_source_columns_to_plugins

Revision ID: 3a42d373bb05
Revises: b5c6d7e8f9a0
Create Date: 2026-08-04 10:52:53.080284
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "3a42d373bb05"
down_revision: str | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = {c["name"] for c in inspect(conn).get_columns("plugins")}
    if "source" not in existing:
        op.add_column(
            "plugins",
            sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        )
    if "external_project_id" not in existing:
        op.add_column("plugins", sa.Column("external_project_id", sa.String(64), nullable=True))
    if "external_version_id" not in existing:
        op.add_column("plugins", sa.Column("external_version_id", sa.String(64), nullable=True))
    if "external_url" not in existing:
        op.add_column("plugins", sa.Column("external_url", sa.String(512), nullable=True))
    if "checksum" not in existing:
        op.add_column("plugins", sa.Column("checksum", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("plugins", "checksum")
    op.drop_column("plugins", "external_url")
    op.drop_column("plugins", "external_version_id")
    op.drop_column("plugins", "external_project_id")
    op.drop_column("plugins", "source")
