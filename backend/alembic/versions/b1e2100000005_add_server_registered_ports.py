"""add server_registered_ports table

Revision ID: b1e2100000005
Revises: b1e2100000004
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1e2100000005"
down_revision: str | None = "b1e2100000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "server_registered_ports",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "server_id",
            sa.String(length=36),
            sa.ForeignKey("servers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("service_type", sa.String(length=32), nullable=False),
        sa.Column("protocol", sa.String(length=8), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("server_id", "service_type", name="uq_server_registered_port_type"),
        sa.UniqueConstraint(
            "server_id", "port", "protocol", name="uq_server_registered_port_protocol"
        ),
    )


def downgrade() -> None:
    op.drop_table("server_registered_ports")
