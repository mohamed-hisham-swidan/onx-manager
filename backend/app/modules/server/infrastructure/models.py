from __future__ import annotations

import json

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.persistence.base import Base, TimestampMixin


class ServerModel(Base, TimestampMixin):
    __tablename__ = "servers"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    server_type = Column(String(32), nullable=False, default="vanilla")
    minecraft_version = Column(String(16), nullable=False)
    memory_min_mb = Column(Integer, nullable=False, default=1024)
    memory_max_mb = Column(Integer, nullable=False, default=2048)
    java_args = Column(Text, nullable=False, default="")
    group_id = Column(String(64), nullable=False, default="default")
    status = Column(String(16), nullable=False, default="created")
    port = Column(Integer, nullable=False, default=25565)
    motd = Column(String(255), nullable=False, default="A Minecraft Server")
    max_players = Column(Integer, nullable=False, default=20)
    gamemode = Column(String(16), nullable=False, default="survival")
    difficulty = Column(String(16), nullable=False, default="easy")
    spawn_protection = Column(Integer, nullable=False, default=16)
    pvp = Column(Boolean, nullable=False, default=True)
    enable_command_block = Column(Boolean, nullable=False, default=False)
    online_mode = Column(Boolean, nullable=False, default=True)
    whitelist_enabled = Column(Boolean, nullable=False, default=False)
    view_distance = Column(Integer, nullable=False, default=10)
    simulation_distance = Column(Integer, nullable=False, default=10)

    provider = Column(String(32), nullable=False, default="local")
    deployment_host = Column(String(255), nullable=True)
    deployment_port = Column(Integer, nullable=True)
    deployment_pid = Column(Integer, nullable=True)
    external_id = Column(String(255), nullable=True)

    location_type = Column(String(16), nullable=False, default="local")
    location_uri = Column(String(1024), nullable=True)
    root_path = Column(String(1024), nullable=True)
    working_directory = Column(String(256), nullable=False, default=".")
    startup_jar = Column(String(256), nullable=False, default="server.jar")
    startup_command = Column(Text, nullable=False, default="")
    primary_world = Column(String(256), nullable=False, default="world")
    uptime_seconds = Column(Float, nullable=False, default=0.0)
    last_crash_time = Column(Float, nullable=True)
    restart_count = Column(Integer, nullable=False, default=0)
    launch_config_json = Column(Text, nullable=True)
    missing_since = Column(DateTime, nullable=True)