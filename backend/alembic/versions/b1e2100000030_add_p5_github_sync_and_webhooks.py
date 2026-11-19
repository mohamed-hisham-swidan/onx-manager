"""add p5 github sync and webhooks

Revision ID: b1e2100000030
Revises: b1e2100000029
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000030"
down_revision: str | None = "b1e2100000029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SERVER_GITHUB_CONNECTIONS_TABLE = "server_github_connections"
SERVER_GITHUB_CONNECTIONS_INDEX = "ix_server_github_connections_server_id"
SERVER_GITHUB_CONNECTIONS_UNIQUE = "uq_server_github_connections_server_id"

GITHUB_WEBHOOK_DELIVERIES_TABLE = "github_webhook_deliveries"
GITHUB_WEBHOOK_DELIVERIES_SERVER_INDEX = "ix_github_webhook_deliveries_server_id"
GITHUB_WEBHOOK_DELIVERIES_RECEIVED_INDEX = (
    "ix_github_webhook_deliveries_server_received"
)
GITHUB_WEBHOOK_DELIVERIES_UNIQUE = "uq_github_webhook_deliveries_server_delivery"


def _index_exists(inspector, table: str, index_name: str) -> bool:
    return index_name in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 1. server_github_connections
    if SERVER_GITHUB_CONNECTIONS_TABLE not in existing_tables:
        op.create_table(
            SERVER_GITHUB_CONNECTIONS_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column(
                "server_id",
                sa.String(length=36),
                sa.ForeignKey("servers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("remote_url", sa.String(length=512), nullable=False),
            sa.Column("auth_method", sa.String(length=32), nullable=False),
            sa.Column("wrapped_credential_dek", sa.LargeBinary(), nullable=False),
            sa.Column(
                "kek_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("credential_nonce", sa.LargeBinary(length=12), nullable=False),
            sa.Column("credential_ciphertext", sa.LargeBinary(), nullable=False),
            sa.Column("credential_hint", sa.String(length=64), nullable=True),
            sa.Column("deploy_public_key", sa.Text(), nullable=True),
            sa.Column("wrapped_webhook_dek", sa.LargeBinary(), nullable=True),
            sa.Column("webhook_kek_version", sa.Integer(), nullable=True),
            sa.Column("webhook_nonce", sa.LargeBinary(length=12), nullable=True),
            sa.Column("webhook_ciphertext", sa.LargeBinary(), nullable=True),
            sa.Column(
                "webhook_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "sync_status",
                sa.String(length=32),
                nullable=False,
                server_default="idle",
            ),
            sa.Column("last_error_code", sa.String(length=64), nullable=True),
            sa.Column("last_error_message", sa.String(length=512), nullable=True),
            sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_push_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("remote_default_branch", sa.String(length=64), nullable=True),
            sa.Column("remote_head_sha", sa.String(length=64), nullable=True),
            sa.Column("branch_sync_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "server_id", name=SERVER_GITHUB_CONNECTIONS_UNIQUE
            ),
        )
        op.create_index(
            SERVER_GITHUB_CONNECTIONS_INDEX,
            SERVER_GITHUB_CONNECTIONS_TABLE,
            ["server_id"],
        )
    else:
        inspector = inspect(connection)
        if not _index_exists(
            inspector, SERVER_GITHUB_CONNECTIONS_TABLE, SERVER_GITHUB_CONNECTIONS_INDEX
        ):
            op.create_index(
                SERVER_GITHUB_CONNECTIONS_INDEX,
                SERVER_GITHUB_CONNECTIONS_TABLE,
                ["server_id"],
            )

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 2. github_webhook_deliveries
    if GITHUB_WEBHOOK_DELIVERIES_TABLE not in existing_tables:
        op.create_table(
            GITHUB_WEBHOOK_DELIVERIES_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column(
                "server_id",
                sa.String(length=36),
                sa.ForeignKey("servers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("delivery_id", sa.String(length=128), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("ref", sa.String(length=256), nullable=True),
            sa.Column("before_sha", sa.String(length=64), nullable=True),
            sa.Column("after_sha", sa.String(length=64), nullable=True),
            sa.Column("payload_sha256", sa.String(length=64), nullable=False),
            sa.Column("raw_payload", sa.Text(), nullable=False),
            sa.Column(
                "signature_valid",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="received",
            ),
            sa.Column("operation_id", sa.String(length=36), nullable=True),
            sa.Column("error_message", sa.String(length=512), nullable=True),
            sa.Column(
                "redelivery_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "server_id",
                "delivery_id",
                name=GITHUB_WEBHOOK_DELIVERIES_UNIQUE,
            ),
        )
        op.create_index(
            GITHUB_WEBHOOK_DELIVERIES_SERVER_INDEX,
            GITHUB_WEBHOOK_DELIVERIES_TABLE,
            ["server_id"],
        )
        op.create_index(
            GITHUB_WEBHOOK_DELIVERIES_RECEIVED_INDEX,
            GITHUB_WEBHOOK_DELIVERIES_TABLE,
            ["server_id", "received_at"],
        )
    else:
        inspector = inspect(connection)
        if not _index_exists(
            inspector,
            GITHUB_WEBHOOK_DELIVERIES_TABLE,
            GITHUB_WEBHOOK_DELIVERIES_SERVER_INDEX,
        ):
            op.create_index(
                GITHUB_WEBHOOK_DELIVERIES_SERVER_INDEX,
                GITHUB_WEBHOOK_DELIVERIES_TABLE,
                ["server_id"],
            )
        inspector = inspect(connection)
        if not _index_exists(
            inspector,
            GITHUB_WEBHOOK_DELIVERIES_TABLE,
            GITHUB_WEBHOOK_DELIVERIES_RECEIVED_INDEX,
        ):
            op.create_index(
                GITHUB_WEBHOOK_DELIVERIES_RECEIVED_INDEX,
                GITHUB_WEBHOOK_DELIVERIES_TABLE,
                ["server_id", "received_at"],
            )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 1. github_webhook_deliveries
    if GITHUB_WEBHOOK_DELIVERIES_TABLE in existing_tables:
        inspector = inspect(connection)
        if _index_exists(
            inspector,
            GITHUB_WEBHOOK_DELIVERIES_TABLE,
            GITHUB_WEBHOOK_DELIVERIES_RECEIVED_INDEX,
        ):
            op.drop_index(
                GITHUB_WEBHOOK_DELIVERIES_RECEIVED_INDEX,
                table_name=GITHUB_WEBHOOK_DELIVERIES_TABLE,
            )
        inspector = inspect(connection)
        if _index_exists(
            inspector,
            GITHUB_WEBHOOK_DELIVERIES_TABLE,
            GITHUB_WEBHOOK_DELIVERIES_SERVER_INDEX,
        ):
            op.drop_index(
                GITHUB_WEBHOOK_DELIVERIES_SERVER_INDEX,
                table_name=GITHUB_WEBHOOK_DELIVERIES_TABLE,
            )
        op.drop_table(GITHUB_WEBHOOK_DELIVERIES_TABLE)

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 2. server_github_connections
    if SERVER_GITHUB_CONNECTIONS_TABLE in existing_tables:
        inspector = inspect(connection)
        if _index_exists(
            inspector, SERVER_GITHUB_CONNECTIONS_TABLE, SERVER_GITHUB_CONNECTIONS_INDEX
        ):
            op.drop_index(
                SERVER_GITHUB_CONNECTIONS_INDEX,
                table_name=SERVER_GITHUB_CONNECTIONS_TABLE,
            )
        op.drop_table(SERVER_GITHUB_CONNECTIONS_TABLE)
