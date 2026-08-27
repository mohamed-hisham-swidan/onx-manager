"""add playit_tunnel_id to server_exposure_target

Revision ID: b1e2100000006
Revises: b1e2100000005
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1e2100000006"
down_revision: str | None = "b1e2100000005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "server_exposure_target",
        sa.Column("playit_tunnel_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("server_exposure_target", "playit_tunnel_id")
