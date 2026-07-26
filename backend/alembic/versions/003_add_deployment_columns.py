"""Add deployment/location columns to servers

Revision ID: 003
Revises: 16f9e2a1f2d6
Create Date: 2026-07-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision: Union[str, None] = "16f9e2a1f2d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("location_type", sa.String(16), nullable=False, server_default="local"))
    op.add_column("servers", sa.Column("location_uri", sa.String(1024), nullable=True))
    op.add_column("servers", sa.Column("root_path", sa.String(1024), nullable=True))
    op.add_column("servers", sa.Column("working_directory", sa.String(256), nullable=False, server_default="."))
    op.add_column("servers", sa.Column("startup_jar", sa.String(256), nullable=False, server_default="server.jar"))
    op.add_column("servers", sa.Column("startup_command", sa.Text(), nullable=False, server_default=""))
    op.add_column("servers", sa.Column("primary_world", sa.String(256), nullable=False, server_default="world"))
    op.add_column("servers", sa.Column("uptime_seconds", sa.Float(), nullable=False, server_default="0.0"))
    op.add_column("servers", sa.Column("last_crash_time", sa.Float(), nullable=True))
    op.add_column("servers", sa.Column("restart_count", sa.Integer(), nullable=False, server_default="0"))

    op.execute("UPDATE servers SET location_type = 'local' WHERE location_type IS NULL")
    op.execute("UPDATE servers SET working_directory = '.' WHERE working_directory IS NULL")
    op.execute("UPDATE servers SET startup_jar = 'server.jar' WHERE startup_jar IS NULL")
    op.execute("UPDATE servers SET startup_command = '' WHERE startup_command IS NULL")
    op.execute("UPDATE servers SET primary_world = 'world' WHERE primary_world IS NULL")
    op.execute("UPDATE servers SET uptime_seconds = 0.0 WHERE uptime_seconds IS NULL")
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