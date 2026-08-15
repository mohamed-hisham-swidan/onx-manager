"""add cloudflare credential columns to server_exposure

Revision ID: b1e2100000004
Revises: b1e2100000003
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1e2100000004"
down_revision: str | None = "b1e2100000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "server_exposure",
        sa.Column("cloudflare_tunnel_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "server_exposure",
        sa.Column("cloudflare_token_ciphertext", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("server_exposure", "cloudflare_token_ciphertext")
    op.drop_column("server_exposure", "cloudflare_tunnel_id")
