"""add playit and upnp columns to panel_exposure

Revision ID: b1e2100000003
Revises: b1e2100000002
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1e2100000003"
down_revision: str | None = "b1e2100000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "panel_exposure",
        sa.Column("external_port", sa.Integer(), nullable=True),
    )
    op.add_column(
        "panel_exposure",
        sa.Column("playit_tunnel_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "panel_exposure",
        sa.Column("upnp_last_result", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "panel_exposure",
        sa.Column("upnp_last_mapped_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("panel_exposure", "upnp_last_mapped_at")
    op.drop_column("panel_exposure", "upnp_last_result")
    op.drop_column("panel_exposure", "playit_tunnel_id")
    op.drop_column("panel_exposure", "external_port")
