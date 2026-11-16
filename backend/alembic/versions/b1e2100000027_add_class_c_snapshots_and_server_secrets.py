"""add encrypted class-c snapshots and server secrets

Revision ID: b1e2100000027
Revises: b1e2100000026
Create Date: 2026-11-16

P3-3 introduces the AES-256-GCM Class-C vault ledger (``class_c_snapshots``)
and the per-record ``${ONX_SECRET_*}`` vault (``server_secrets``).

Operator runbook (M1 / M5)
--------------------------
The master KEK is irreplaceable: losing ``ONX_MASTER_KEK`` /
``ONX_MASTER_KEK_FILE`` permanently destroys the ability to restore every
``format_version = 2`` snapshot and every extracted secret. Generate a 32-byte
key once, keep it on a ``0600`` file, and store an encrypted offline backup
before enabling Advanced mode.

``format_version = 1`` plain snapshots are retired and fail closed. Before
upgrading an existing installation:

1. Verify no open refresh journal references a snapshot:
   ``SELECT journal_id, server_id, phase, class_c_snapshot_id
   FROM refresh_journals WHERE terminal = 0;``
2. Settle or reconcile every open journal. This migration refuses to run while
   an open (``terminal = 0``) journal has a non-empty ``class_c_snapshot_id``.
3. Delete pre-P3 plain ``<host_state>/class-c-vault/<server_id>/<snapshot_id>``
   directories whose ``manifest.json`` has ``"format_version": 1``.
4. Run ``alembic upgrade head``.

Caveat (M5): deleting a v1 snapshot that is referenced by a historical
*terminal* journal forfeits pre-P3 triad rollback to that snapshot.

``downgrade()`` only drops the two SQL tables and their indexes. It never
deletes on-disk snapshot files.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000027"
down_revision: str | None = "b1e2100000026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLASS_C_SNAPSHOTS_TABLE = "class_c_snapshots"
SERVER_SECRETS_TABLE = "server_secrets"
SERVER_ID_INDEX = "ix_class_c_snapshots_server_id"
SERVER_CREATED_INDEX = "ix_class_c_snapshots_server_created_at"
SERVER_SECRETS_INDEX = "ix_server_secrets_server_id"


def _assert_no_open_v1_journal(connection: sa.Connection) -> None:
    inspector = inspect(connection)
    if not inspector.has_table("refresh_journals"):
        return
    rows = connection.execute(
        sa.text(
            "SELECT journal_id, server_id, phase, class_c_snapshot_id "
            "FROM refresh_journals "
            "WHERE terminal = :term "
            "AND class_c_snapshot_id IS NOT NULL "
            "AND class_c_snapshot_id != ''"
        ),
        {"term": False},
    ).fetchall()
    if not rows:
        return
    details = "\n".join(
        f"  journal_id={row[0]} server_id={row[1]} phase={row[2]} class_c_snapshot_id={row[3]}"
        for row in rows
    )
    raise RuntimeError(
        "Cannot upgrade to b1e2100000027: open (terminal = 0) refresh journals "
        "reference pre-P3 format_version=1 Class-C snapshots. Settle or reconcile "
        "each open journal and remove its plain snapshot directory before retrying.\n"
        f"{details}"
    )


def upgrade() -> None:
    connection = op.get_bind()
    _assert_no_open_v1_journal(connection)

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    if CLASS_C_SNAPSHOTS_TABLE not in existing_tables:
        op.create_table(
            CLASS_C_SNAPSHOTS_TABLE,
            sa.Column("snapshot_id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column(
                "server_id",
                sa.String(length=36),
                sa.ForeignKey("servers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
            sa.Column(
                "kek_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column(
                "file_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "total_bytes",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "pinned",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="active",
            ),
        )
        op.create_index(SERVER_ID_INDEX, CLASS_C_SNAPSHOTS_TABLE, ["server_id"])
        op.create_index(
            SERVER_CREATED_INDEX,
            CLASS_C_SNAPSHOTS_TABLE,
            ["server_id", "created_at"],
        )

    if SERVER_SECRETS_TABLE not in existing_tables:
        op.create_table(
            SERVER_SECRETS_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column(
                "server_id",
                sa.String(length=36),
                sa.ForeignKey("servers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("key_name", sa.String(length=128), nullable=False),
            sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
            sa.Column(
                "kek_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("nonce", sa.LargeBinary(length=12), nullable=False),
            sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "server_id", "key_name", name="uq_server_secrets_server_key"
            ),
        )
        op.create_index(SERVER_SECRETS_INDEX, SERVER_SECRETS_TABLE, ["server_id"])


def downgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    if SERVER_SECRETS_TABLE in existing_tables:
        existing_indexes = {
            index["name"] for index in inspector.get_indexes(SERVER_SECRETS_TABLE)
        }
        if SERVER_SECRETS_INDEX in existing_indexes:
            op.drop_index(SERVER_SECRETS_INDEX, table_name=SERVER_SECRETS_TABLE)
        op.drop_table(SERVER_SECRETS_TABLE)

    if CLASS_C_SNAPSHOTS_TABLE in existing_tables:
        existing_indexes = {
            index["name"] for index in inspector.get_indexes(CLASS_C_SNAPSHOTS_TABLE)
        }
        for index_name in (SERVER_CREATED_INDEX, SERVER_ID_INDEX):
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name=CLASS_C_SNAPSHOTS_TABLE)
        op.drop_table(CLASS_C_SNAPSHOTS_TABLE)
