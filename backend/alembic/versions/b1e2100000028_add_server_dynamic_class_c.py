"""add server dynamic class c

Revision ID: b1e2100000028
Revises: b1e2100000027
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000028"
down_revision: str | None = "b1e2100000027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "server_dynamic_class_c"
INDEX = "ix_server_dynamic_class_c_server_id"
CONSTRAINT = "uq_server_dynamic_class_c_path"


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    if TABLE not in existing_tables:
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column(
                "server_id",
                sa.String(length=36),
                sa.ForeignKey("servers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("relpath", sa.String(length=512), nullable=False),
            sa.Column(
                "reason",
                sa.String(length=128),
                nullable=False,
                server_default="ast_diverged",
            ),
            sa.Column("baseline_ast_sha256", sa.String(length=64), nullable=True),
            sa.Column("live_ast_sha256", sa.String(length=64), nullable=True),
            sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("server_id", "relpath", name=CONSTRAINT),
        )
        op.create_index(INDEX, TABLE, ["server_id"])


def downgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    if TABLE in existing_tables:
        existing_indexes = {
            index["name"] for index in inspector.get_indexes(TABLE)
        }
        if INDEX in existing_indexes:
            op.drop_index(INDEX, table_name=TABLE)
        op.drop_table(TABLE)
