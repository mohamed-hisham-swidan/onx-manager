from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
    cpu_cores = Column(Integer, nullable=True, default=0)
    cpu_affinity = Column(String(64), nullable=True, default="")
    group_id = Column(String(64), nullable=False, default="default")
    status = Column(String(32), nullable=False, default="created")
    provisioning_error = Column(Text, nullable=True)
    provisioning_retryable = Column(Boolean, nullable=False, default=False)
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

    provider = Column(String(32), nullable=False, default="")
    deployment_host = Column(String(255), nullable=True)
    deployment_port = Column(Integer, nullable=True)
    deployment_pid = Column(Integer, nullable=True)
    deployment_start_time = Column(Integer, nullable=True)
    running_start_time = Column(Float, nullable=True)
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
    bot_verification_settings = Column(JSON, nullable=True)
    missing_since = Column(DateTime, nullable=True)
    owner_id = Column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    owner = relationship("UserModel", foreign_keys=[owner_id], back_populates="owned_servers")
    memberships = relationship(
        "ServerMembershipModel", back_populates="server", cascade="all, delete-orphan"
    )


class ServerMembershipModel(Base, TimestampMixin):
    __tablename__ = "server_memberships"

    id = Column(String(36), primary_key=True)
    server_id = Column(
        String(36), ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role = Column(String(32), nullable=False)

    server = relationship("ServerModel", back_populates="memberships")
    user = relationship("UserModel", back_populates="server_memberships")

    __table_args__ = (UniqueConstraint("server_id", "user_id", name="uq_server_user_membership"),)
