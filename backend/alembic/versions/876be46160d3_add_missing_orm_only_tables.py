"""add_missing_orm_only_tables

This migration retroactively creates tables that were historically
created only via Base.metadata.create_all() during early development
and never captured as Alembic migrations.  A fresh clone running
``alembic upgrade head`` alone would fail at migration 003 with
"no such table: servers".

Tables created: servers, api_keys, audit_log, backup_jobs,
backup_policies, plugins, refresh_tokens, roles, user_roles.

Revision ID: 876be46160d3
Revises: 902b076bfa36
Create Date: 2026-07-26 20:55:44.692785
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa


revision: str = "876be46160d3"
down_revision: Union[str, None] = "902b076bfa36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    """Return True if the table already exists in the current database."""
    conn = op.get_bind()
    inspector = inspect(conn)
    return name in inspector.get_table_names()


def upgrade() -> None:
    # ── servers ──────────────────────────────────────────────
    if not _table_exists("servers"):
        op.create_table(
            "servers",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("server_type", sa.String(32), nullable=False, server_default="vanilla"),
            sa.Column("minecraft_version", sa.String(16), nullable=False),
            sa.Column("memory_min_mb", sa.Integer, nullable=False, server_default="1024"),
            sa.Column("memory_max_mb", sa.Integer, nullable=False, server_default="2048"),
            sa.Column("java_args", sa.Text, nullable=False, server_default=""),
            sa.Column("group_id", sa.String(64), nullable=False, server_default="default"),
            sa.Column("status", sa.String(16), nullable=False, server_default="created"),
            sa.Column("port", sa.Integer, nullable=False, server_default="25565"),
            sa.Column("motd", sa.String(255), nullable=False, server_default="A Minecraft Server"),
            sa.Column("max_players", sa.Integer, nullable=False, server_default="20"),
            sa.Column("gamemode", sa.String(16), nullable=False, server_default="survival"),
            sa.Column("difficulty", sa.String(16), nullable=False, server_default="easy"),
            sa.Column("spawn_protection", sa.Integer, nullable=False, server_default="16"),
            sa.Column("pvp", sa.Boolean, nullable=False, server_default=sa.text("1")),
            sa.Column("enable_command_block", sa.Boolean, nullable=False, server_default=sa.text("0")),
            sa.Column("online_mode", sa.Boolean, nullable=False, server_default=sa.text("1")),
            sa.Column("whitelist_enabled", sa.Boolean, nullable=False, server_default=sa.text("0")),
            sa.Column("view_distance", sa.Integer, nullable=False, server_default="10"),
            sa.Column("simulation_distance", sa.Integer, nullable=False, server_default="10"),
            sa.Column("provider", sa.String(32), nullable=False, server_default="local"),
            sa.Column("deployment_host", sa.String(255), nullable=True),
            sa.Column("deployment_port", sa.Integer, nullable=True),
            sa.Column("deployment_pid", sa.Integer, nullable=True),
            sa.Column("external_id", sa.String(255), nullable=True),
            sa.Column("location_type", sa.String(16), nullable=False, server_default="local"),
            sa.Column("location_uri", sa.String(1024), nullable=True),
            sa.Column("root_path", sa.String(1024), nullable=True),
            sa.Column("working_directory", sa.String(256), nullable=False, server_default="."),
            sa.Column("startup_jar", sa.String(256), nullable=False, server_default="server.jar"),
            sa.Column("startup_command", sa.Text, nullable=False, server_default=""),
            sa.Column("primary_world", sa.String(256), nullable=False, server_default="world"),
            sa.Column("uptime_seconds", sa.Float, nullable=False, server_default="0.0"),
            sa.Column("last_crash_time", sa.Float, nullable=True),
            sa.Column("restart_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("launch_config_json", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    # ── api_keys ────────────────────────────────────────────
    if not _table_exists("api_keys"):
        op.create_table(
            "api_keys",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("prefix", sa.String(16), nullable=False),
            sa.Column("key_hash", sa.String(128), nullable=False),
            sa.Column("permissions", sa.Text, nullable=False, server_default=""),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_revoked", sa.Boolean, nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])

    # ── audit_log ───────────────────────────────────────────
    if not _table_exists("audit_log"):
        op.create_table(
            "audit_log",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("actor_type", sa.String(32), nullable=False),
            sa.Column("actor_id", sa.String(255), nullable=False),
            sa.Column("action", sa.String(128), nullable=False),
            sa.Column("resource_type", sa.String(128), nullable=False),
            sa.Column("resource_id", sa.String(255), nullable=False),
            sa.Column("old_value", sa.Text, nullable=True),
            sa.Column("new_value", sa.Text, nullable=True),
            sa.Column("ip_address", sa.String(64), nullable=True),
            sa.Column("user_agent", sa.String(512), nullable=True),
            sa.Column("outcome", sa.String(32), nullable=False),
            sa.Column("correlation_id", sa.String(64), nullable=False),
            sa.Column("previous_hash", sa.String(64), nullable=False),
            sa.Column("hash", sa.String(64), nullable=False, unique=True),
        )

    # ── backup_jobs ─────────────────────────────────────────
    if not _table_exists("backup_jobs"):
        op.create_table(
            "backup_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("server_id", sa.String(36), nullable=False),
            sa.Column("backup_type", sa.String(16), nullable=False, server_default="full"),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("size_bytes", sa.Integer, nullable=False, server_default="0"),
            sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("storage_path", sa.String(512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_backup_jobs_server_id", "backup_jobs", ["server_id"])

    # ── backup_policies ─────────────────────────────────────
    if not _table_exists("backup_policies"):
        op.create_table(
            "backup_policies",
            sa.Column("server_id", sa.String(36), primary_key=True),
            sa.Column("schedule", sa.String(128), nullable=False),
            sa.Column("retention_days", sa.Integer, nullable=False, server_default="30"),
            sa.Column("backup_type", sa.String(16), nullable=False, server_default="full"),
            sa.Column("encryption_enabled", sa.Boolean, nullable=False, server_default=sa.text("1")),
            sa.Column("max_backups", sa.Integer, nullable=False, server_default="50"),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    # ── plugins ─────────────────────────────────────────────
    if not _table_exists("plugins"):
        op.create_table(
            "plugins",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("server_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("version", sa.String(32), nullable=False),
            sa.Column("description", sa.Text, nullable=False, server_default=""),
            sa.Column("author", sa.String(128), nullable=False, server_default=""),
            sa.Column("website", sa.String(512), nullable=False, server_default=""),
            sa.Column("dependencies", sa.Text, nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="installed"),
            sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            # PluginModel overrides TimestampMixin.updated_at to nullable
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_plugins_server_id", "plugins", ["server_id"])

    # ── refresh_tokens ──────────────────────────────────────
    if not _table_exists("refresh_tokens"):
        op.create_table(
            "refresh_tokens",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_revoked", sa.Boolean, nullable=False, server_default=sa.text("0")),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    # ── roles ───────────────────────────────────────────────
    if not _table_exists("roles"):
        op.create_table(
            "roles",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False, unique=True),
            sa.Column("description", sa.Text, nullable=False, server_default=""),
            sa.Column("permissions", sa.Text, nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    # ── user_roles (many-to-many join, no TimestampMixin) ───
    if not _table_exists("user_roles"):
        op.create_table(
            "user_roles",
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        )


def downgrade() -> None:
    # Drop in reverse dependency order (FK targets last)
    tables = [
        "user_roles",
        "api_keys",
        "refresh_tokens",
        "plugins",
        "backup_jobs",
        "backup_policies",
        "audit_log",
        "roles",
        "servers",
    ]
    for t in tables:
        if _table_exists(t):
            op.drop_table(t)
