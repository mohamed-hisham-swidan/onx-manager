"""Add deployment/location columns to servers

Revision ID: 003
Revises: 16f9e2a1f2d6
Create Date: 2026-07-23

NOTE: modified post-hoc to create the ``servers`` table on a fresh database
(rather than assuming ``Base.metadata.create_all()`` was run first).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "003"
down_revision: str | None = "16f9e2a1f2d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    if "servers" not in inspector.get_table_names():
        # Fresh database ── create servers with all columns (ORM + deployment)
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
            sa.Column(
                "enable_command_block", sa.Boolean, nullable=False, server_default=sa.text("0")
            ),
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
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        return

    # Existing database ── add deployment columns one at a time if missing
    existing = {c["name"] for c in inspector.get_columns("servers")}

    deployment_columns = [
        ("location_type", sa.String(16), False, "local"),
        ("location_uri", sa.String(1024), True, None),
        ("root_path", sa.String(1024), True, None),
        ("working_directory", sa.String(256), False, "."),
        ("startup_jar", sa.String(256), False, "server.jar"),
        ("startup_command", sa.Text(), False, ""),
        ("primary_world", sa.String(256), False, "world"),
        ("uptime_seconds", sa.Float(), False, "0.0"),
        ("last_crash_time", sa.Float(), True, None),
        ("restart_count", sa.Integer(), False, "0"),
    ]

    added = []
    for name, type_, nullable, default in deployment_columns:
        if name not in existing:
            kwargs = {"nullable": nullable}
            if default is not None:
                kwargs["server_default"] = default
            op.add_column("servers", sa.Column(name, type_, **kwargs))
            added.append(name)

    if "location_type" in added:
        op.execute("UPDATE servers SET location_type = 'local' WHERE location_type IS NULL")
    if "working_directory" in added:
        op.execute("UPDATE servers SET working_directory = '.' WHERE working_directory IS NULL")
    if "startup_jar" in added:
        op.execute("UPDATE servers SET startup_jar = 'server.jar' WHERE startup_jar IS NULL")
    if "startup_command" in added:
        op.execute("UPDATE servers SET startup_command = '' WHERE startup_command IS NULL")
    if "primary_world" in added:
        op.execute("UPDATE servers SET primary_world = 'world' WHERE primary_world IS NULL")
    if "uptime_seconds" in added:
        op.execute("UPDATE servers SET uptime_seconds = 0.0 WHERE uptime_seconds IS NULL")
    if "restart_count" in added:
        op.execute("UPDATE servers SET restart_count = 0 WHERE restart_count IS NULL")


def downgrade() -> None:
    op.drop_column("servers", "restart_count")
    op.drop_column("servers", "last_crash_time")
    op.drop_column("servers", "uptime_seconds")
    op.drop_column("servers", "primary_world")
    op.drop_column("servers", "startup_command")
    op.drop_column("servers", "startup_jar")
    op.drop_column("servers", "working_directory")
    op.drop_column("servers", "root_path")
    op.drop_column("servers", "location_uri")
    op.drop_column("servers", "location_type")
