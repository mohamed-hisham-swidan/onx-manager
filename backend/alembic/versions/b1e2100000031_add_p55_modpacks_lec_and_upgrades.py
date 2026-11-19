"""add p55 modpacks lec and upgrades

Revision ID: b1e2100000031
Revises: b1e2100000030
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "b1e2100000031"
down_revision: str | None = "b1e2100000030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SERVER_UPGRADES_TABLE = "server_upgrades"
SERVER_UPGRADES_SERVER_INDEX = "ix_server_upgrades_server_id"
SERVER_UPGRADES_STATUS_INDEX = "ix_server_upgrades_server_status"
SERVER_UPGRADES_CREATED_INDEX = "ix_server_upgrades_server_created"

LOADER_ENV_CACHE_TABLE = "loader_env_cache_entries"
LOADER_ENV_CACHE_LOADER_MC_INDEX = "ix_loader_env_cache_entries_loader_mc"
LOADER_ENV_CACHE_LAST_USED_INDEX = "ix_loader_env_cache_entries_last_used"

PANEL_INTEGRATION_SECRETS_TABLE = "panel_integration_secrets"

SERVER_COLUMNS = (
    "health_gate_boot_timeout_seconds",
    "install_optional_server_files",
    "allow_experimental_paper_builds",
    "download_host_allowlist_json",
)


def _existing_columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def _add_column_if_missing(inspector, table: str, column: sa.Column) -> None:
    if column.name not in _existing_columns(inspector, table):
        op.add_column(table, column)


def _index_exists(inspector, table: str, index_name: str) -> bool:
    return index_name in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 1. servers: P5.5 upgrade/health-gate/download columns.
    if "servers" in existing_tables:
        inspector = inspect(connection)
        _add_column_if_missing(
            inspector,
            "servers",
            sa.Column(
                "health_gate_boot_timeout_seconds",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("300"),
            ),
        )
        _add_column_if_missing(
            inspector,
            "servers",
            sa.Column(
                "install_optional_server_files",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )
        _add_column_if_missing(
            inspector,
            "servers",
            sa.Column(
                "allow_experimental_paper_builds",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
        _add_column_if_missing(
            inspector,
            "servers",
            sa.Column("download_host_allowlist_json", sa.JSON(), nullable=True),
        )

    # 2. server_upgrades
    if SERVER_UPGRADES_TABLE not in existing_tables:
        op.create_table(
            SERVER_UPGRADES_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column(
                "server_id",
                sa.String(length=36),
                sa.ForeignKey("servers.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "kind",
                sa.String(length=32),
                nullable=False,
                server_default="server_upgrade",
            ),
            sa.Column(
                "mode",
                sa.String(length=16),
                nullable=False,
                server_default="simple",
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="planned",
            ),
            sa.Column("source_mc", sa.String(length=32), nullable=True),
            sa.Column("target_mc", sa.String(length=32), nullable=False),
            sa.Column("source_loader_id", sa.String(length=32), nullable=True),
            sa.Column("source_loader_version", sa.String(length=64), nullable=True),
            sa.Column("target_loader_id", sa.String(length=32), nullable=False),
            sa.Column("target_loader_version", sa.String(length=64), nullable=False),
            sa.Column("target_lec_key", sa.String(length=256), nullable=True),
            sa.Column("upgrade_branch", sa.String(length=128), nullable=True),
            sa.Column("operation_id", sa.String(length=36), nullable=True),
            sa.Column("journal_id", sa.String(length=36), nullable=True),
            sa.Column("previous_main_sha", sa.String(length=64), nullable=True),
            sa.Column("target_main_sha", sa.String(length=64), nullable=True),
            sa.Column("pre_upgrade_backup_id", sa.String(length=36), nullable=True),
            sa.Column("class_c_snapshot_id", sa.String(length=36), nullable=True),
            sa.Column("data_template_id", sa.String(length=36), nullable=True),
            sa.Column("plan_json", sa.JSON(), nullable=True),
            sa.Column("matrix_json", sa.JSON(), nullable=True),
            sa.Column("manual_blockers_json", sa.JSON(), nullable=True),
            sa.Column(
                "pinned_until_confirm",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "health_gate_passed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("error_message", sa.String(length=512), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            SERVER_UPGRADES_SERVER_INDEX,
            SERVER_UPGRADES_TABLE,
            ["server_id"],
        )
        op.create_index(
            SERVER_UPGRADES_STATUS_INDEX,
            SERVER_UPGRADES_TABLE,
            ["server_id", "status"],
        )
        op.create_index(
            SERVER_UPGRADES_CREATED_INDEX,
            SERVER_UPGRADES_TABLE,
            ["server_id", "created_at"],
        )
    else:
        inspector = inspect(connection)
        for index_name, columns in (
            (SERVER_UPGRADES_SERVER_INDEX, ["server_id"]),
            (SERVER_UPGRADES_STATUS_INDEX, ["server_id", "status"]),
            (SERVER_UPGRADES_CREATED_INDEX, ["server_id", "created_at"]),
        ):
            if not _index_exists(inspector, SERVER_UPGRADES_TABLE, index_name):
                op.create_index(index_name, SERVER_UPGRADES_TABLE, columns)

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 3. loader_env_cache_entries
    if LOADER_ENV_CACHE_TABLE not in existing_tables:
        op.create_table(
            LOADER_ENV_CACHE_TABLE,
            sa.Column("lec_key", sa.String(length=256), primary_key=True, nullable=False),
            sa.Column("loader_id", sa.String(length=32), nullable=False),
            sa.Column("mc_version", sa.String(length=32), nullable=False),
            sa.Column("loader_version", sa.String(length=64), nullable=False),
            sa.Column("installer_version", sa.String(length=64), nullable=True),
            sa.Column("java_major", sa.Integer(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="ready",
            ),
            sa.Column(
                "size_bytes",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "file_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("complete_manifest_sha256", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            LOADER_ENV_CACHE_LOADER_MC_INDEX,
            LOADER_ENV_CACHE_TABLE,
            ["loader_id", "mc_version"],
        )
        op.create_index(
            LOADER_ENV_CACHE_LAST_USED_INDEX,
            LOADER_ENV_CACHE_TABLE,
            ["last_used_at"],
        )
    else:
        inspector = inspect(connection)
        if not _index_exists(
            inspector, LOADER_ENV_CACHE_TABLE, LOADER_ENV_CACHE_LOADER_MC_INDEX
        ):
            op.create_index(
                LOADER_ENV_CACHE_LOADER_MC_INDEX,
                LOADER_ENV_CACHE_TABLE,
                ["loader_id", "mc_version"],
            )
        if not _index_exists(
            inspector, LOADER_ENV_CACHE_TABLE, LOADER_ENV_CACHE_LAST_USED_INDEX
        ):
            op.create_index(
                LOADER_ENV_CACHE_LAST_USED_INDEX,
                LOADER_ENV_CACHE_TABLE,
                ["last_used_at"],
            )

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 4. panel_integration_secrets
    if PANEL_INTEGRATION_SECRETS_TABLE not in existing_tables:
        op.create_table(
            PANEL_INTEGRATION_SECRETS_TABLE,
            sa.Column(
                "integration_key",
                sa.String(length=64),
                primary_key=True,
                nullable=False,
            ),
            sa.Column(
                "encryption_mode",
                sa.String(length=32),
                nullable=False,
                server_default="master_kek_v1",
            ),
            sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
            sa.Column(
                "kek_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("nonce", sa.LargeBinary(length=12), nullable=False),
            sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
            sa.Column("key_hint", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 1. panel_integration_secrets
    if PANEL_INTEGRATION_SECRETS_TABLE in existing_tables:
        op.drop_table(PANEL_INTEGRATION_SECRETS_TABLE)

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 2. loader_env_cache_entries
    if LOADER_ENV_CACHE_TABLE in existing_tables:
        inspector = inspect(connection)
        if _index_exists(
            inspector, LOADER_ENV_CACHE_TABLE, LOADER_ENV_CACHE_LAST_USED_INDEX
        ):
            op.drop_index(
                LOADER_ENV_CACHE_LAST_USED_INDEX,
                table_name=LOADER_ENV_CACHE_TABLE,
            )
        inspector = inspect(connection)
        if _index_exists(
            inspector, LOADER_ENV_CACHE_TABLE, LOADER_ENV_CACHE_LOADER_MC_INDEX
        ):
            op.drop_index(
                LOADER_ENV_CACHE_LOADER_MC_INDEX,
                table_name=LOADER_ENV_CACHE_TABLE,
            )
        op.drop_table(LOADER_ENV_CACHE_TABLE)

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 3. server_upgrades
    if SERVER_UPGRADES_TABLE in existing_tables:
        inspector = inspect(connection)
        for index_name in (
            SERVER_UPGRADES_CREATED_INDEX,
            SERVER_UPGRADES_STATUS_INDEX,
            SERVER_UPGRADES_SERVER_INDEX,
        ):
            if _index_exists(inspector, SERVER_UPGRADES_TABLE, index_name):
                op.drop_index(index_name, table_name=SERVER_UPGRADES_TABLE)
            inspector = inspect(connection)
        op.drop_table(SERVER_UPGRADES_TABLE)

    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    # 4. servers columns
    if "servers" in existing_tables:
        inspector = inspect(connection)
        cols = _existing_columns(inspector, "servers")
        with op.batch_alter_table("servers") as batch_op:
            for name in SERVER_COLUMNS:
                if name in cols:
                    batch_op.drop_column(name)
