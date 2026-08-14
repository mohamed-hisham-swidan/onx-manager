"""add cloudflare credential columns to panel_exposure

Revision ID: b1e2100000002
Revises: b1e2100000001
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1e2100000002"
down_revision: str | None = "b1e2100000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "panel_exposure",
        sa.Column("cloudflare_tunnel_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "panel_exposure",
        sa.Column("cloudflare_token_ciphertext", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("panel_exposure", "cloudflare_token_ciphertext")
    op.drop_column("panel_exposure", "cloudflare_tunnel_id")
