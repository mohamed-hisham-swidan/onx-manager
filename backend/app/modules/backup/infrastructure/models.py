from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.core.persistence.base import Base, TimestampMixin


class BackupJobModel(Base, TimestampMixin):
    __tablename__ = "backup_jobs"

    id = Column(String(36), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    backup_type = Column(String(16), nullable=False, default="full")
    status = Column(String(16), nullable=False, default="pending")
    size_bytes = Column(Integer, nullable=False, default=0)
    checksum = Column(String(64), nullable=False, default="")
    error_message = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    storage_path = Column(String(512), nullable=True)
    pinned = Column(Boolean, nullable=False, default=False)
    tier = Column(String(16), nullable=False, default="tier_1")


class BackupPolicyModel(Base, TimestampMixin):
    __tablename__ = "backup_policies"

    server_id = Column(String(36), primary_key=True)
    schedule = Column(String(128), nullable=False)
    retention_days = Column(Integer, nullable=False, default=30)
    backup_type = Column(String(16), nullable=False, default="full")
    encryption_enabled = Column(Boolean, nullable=False, default=True)
    max_backups = Column(Integer, nullable=False, default=50)
    enabled = Column(Boolean, nullable=False, default=True)


class PendingRestoreModel(Base, TimestampMixin):
    __tablename__ = "pending_restores"

    server_id = Column(String(36), primary_key=True)
    backup_id = Column(String(36), nullable=False)
    requested_at = Column(DateTime(timezone=True), nullable=False)
