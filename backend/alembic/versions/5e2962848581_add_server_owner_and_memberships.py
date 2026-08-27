"""add_server_owner_and_memberships

Revision ID: 5e2962848581
Revises: 989743c08820
Create Date: 2026-08-11 10:06:30.749706
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5e2962848581"
down_revision: str | None = "989743c08820"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add owner_id to servers table using batch_alter_table for SQLite compatibility
    with op.batch_alter_table("servers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("owner_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_servers_owner_id_users", "users", ["owner_id"], ["id"], ondelete="SET NULL"
        )

    # Create server_memberships table
    op.create_table(
        "server_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("server_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "user_id", name="uq_server_user_membership"),
    )
    op.create_index(
        op.f("ix_server_memberships_server_id"), "server_memberships", ["server_id"], unique=False
    )
    op.create_index(
        op.f("ix_server_memberships_user_id"), "server_memberships", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_server_memberships_user_id"), table_name="server_memberships")
    op.drop_index(op.f("ix_server_memberships_server_id"), table_name="server_memberships")
    op.drop_table("server_memberships")

    with op.batch_alter_table("servers", schema=None) as batch_op:
        batch_op.drop_constraint("fk_servers_owner_id_users", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_servers_owner_id"))
        batch_op.drop_column("owner_id")
