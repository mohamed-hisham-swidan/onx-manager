from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.persistence.base import Base, TimestampMixin


def _default_username(context) -> str:
    params = context.get_current_parameters() or {}
    for key in ("email", "display_name", "id"):
        raw = params.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()[:128]
    return "user"


class UserModel(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    username = Column(
        String(128), nullable=False, unique=True, index=True, default=_default_username
    )
    email = Column(String(255), nullable=True, unique=True)
    password_hash = Column(String(512), nullable=False)
    display_name = Column(String(128), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    denied_permissions = Column(JSON, nullable=False, default=list)
    all_servers_access = Column(Boolean, nullable=False, default=False)
    roles = relationship(
        "RoleModel", secondary="user_roles", back_populates="users", lazy="selectin"
    )
    owned_servers = relationship(
        "ServerModel", foreign_keys="[ServerModel.owner_id]", back_populates="owner"
    )
    server_memberships = relationship(
        "ServerMembershipModel", back_populates="user", cascade="all, delete-orphan"
    )


class RoleModel(Base, TimestampMixin):
    __tablename__ = "roles"

    id = Column(String(36), primary_key=True)
    name = Column(String(128), nullable=False, unique=True)
    description = Column(Text, nullable=False, default="")
    permissions = Column(Text, nullable=False, default="")
    users = relationship(
        "UserModel", secondary="user_roles", back_populates="roles", lazy="selectin"
    )


class UserRoleModel(Base):
    __tablename__ = "user_roles"

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)


class ApiKeyModel(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True)
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(128), nullable=False)
    prefix = Column(String(16), nullable=False)
    key_hash = Column(String(128), nullable=False)
    permissions = Column(Text, nullable=False, default="")
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_revoked = Column(Boolean, nullable=False, default=False)


class RefreshTokenModel(Base, TimestampMixin):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = Column(String(128), nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, nullable=False, default=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class SystemStateModel(Base, TimestampMixin):
    __tablename__ = "system_state"

    id = Column(String(36), primary_key=True, default="default")
    initialized = Column(Boolean, nullable=False, default=False)
    access_mode = Column(String(32), nullable=False, default="LOCAL")
    password_configured = Column(Boolean, nullable=False, default=True)


class InvitationModel(Base, TimestampMixin):
    __tablename__ = "invitations"

    id = Column(String(36), primary_key=True)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    token_prefix = Column(String(16), nullable=False)
    creator_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    email = Column(String(255), nullable=True, index=True)
    global_role = Column(String(32), nullable=False, default="viewer")
    server_id = Column(String(36), ForeignKey("servers.id", ondelete="CASCADE"), nullable=True)
    server_role = Column(String(32), nullable=True)
    server_ids_json = Column(JSON, nullable=False, default=list)
    denied_permissions_json = Column(JSON, nullable=False, default=list)
    all_servers_access = Column(Boolean, nullable=False, default=False)
    status = Column(String(32), nullable=False, default="ACTIVE")
    max_uses = Column(Integer, nullable=False, default=1)
    use_count = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (CheckConstraint("use_count <= max_uses", name="ck_invitation_use_count"),)
