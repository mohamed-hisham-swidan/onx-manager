from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)

from app.core.persistence.base import Base, TimestampMixin


class HostPlayitAgentModel(Base, TimestampMixin):
    __tablename__ = "host_playit_agent"

    id = Column(String(36), primary_key=True, default="default")
    secret_ciphertext = Column(LargeBinary, nullable=True)
    claim_code = Column(String(255), nullable=True)
    claim_expires_at = Column(DateTime(timezone=True), nullable=True)
    process_status = Column(String(16), nullable=False, default="STOPPED")
    last_health_at = Column(DateTime(timezone=True), nullable=True)
    desired_agent_running = Column(Boolean, nullable=False, default=False)


class ServerExposureModel(Base, TimestampMixin):
    __tablename__ = "server_exposure"

    id = Column(String(36), primary_key=True)
    server_id = Column(
        String(36),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    method = Column(String(16), nullable=False)
    desired_state = Column(String(16), nullable=False, default="DISABLED")
    aggregate_status = Column(String(32), nullable=False, default="DISABLED")


class ServerExposureTargetModel(Base, TimestampMixin):
    __tablename__ = "server_exposure_target"

    id = Column(String(36), primary_key=True)
    exposure_id = Column(
        String(36),
        ForeignKey("server_exposure.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    protocol = Column(String(8), nullable=False, default="tcp")
    service_type = Column(String(16), nullable=False, default="java")
    local_port = Column(Integer, nullable=False)
    public_address = Column(String(512), nullable=True)
    status = Column(String(32), nullable=False, default="DISABLED")
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "exposure_id",
            "service_type",
            "protocol",
            name="uq_exposure_target_service_protocol",
        ),
    )


class PanelExposureModel(Base, TimestampMixin):
    __tablename__ = "panel_exposure"

    id = Column(String(36), primary_key=True, default="default")
    method = Column(String(32), nullable=False, default="none")
    desired_state = Column(String(16), nullable=False, default="DISABLED")
    status = Column(String(32), nullable=False, default="DISABLED")
    public_address = Column(String(512), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)


class ServerExposureGrantModel(Base, TimestampMixin):
    __tablename__ = "server_exposure_grants"

    id = Column(String(36), primary_key=True)
    server_id = Column(
        String(36),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    can_manage = Column(Boolean, nullable=False, default=False)
    can_view = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("server_id", "user_id", name="uq_exposure_grant_server_user"),
    )
