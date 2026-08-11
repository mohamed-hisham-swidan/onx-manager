from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.persistence.base import Base, TimestampMixin


class UserModel(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(512), nullable=False)
    display_name = Column(String(128), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    roles = relationship("RoleModel", secondary="user_roles", back_populates="users", lazy="selectin")
    owned_servers = relationship("ServerModel", foreign_keys="[ServerModel.owner_id]", back_populates="owner")
    server_memberships = relationship("ServerMembershipModel", back_populates="user", cascade="all, delete-orphan")



class RoleModel(Base, TimestampMixin):
    __tablename__ = "roles"

    id = Column(String(36), primary_key=True)
    name = Column(String(128), nullable=False, unique=True)
    description = Column(Text, nullable=False, default="")
    permissions = Column(Text, nullable=False, default="")
    users = relationship("UserModel", secondary="user_roles", back_populates="roles", lazy="selectin")


class UserRoleModel(Base):
    __tablename__ = "user_roles"

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)


class ApiKeyModel(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    prefix = Column(String(16), nullable=False)
    key_hash = Column(String(128), nullable=False)
    permissions = Column(Text, nullable=False, default="")
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_revoked = Column(Boolean, nullable=False, default=False)


class RefreshTokenModel(Base, TimestampMixin):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, nullable=False, default=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
