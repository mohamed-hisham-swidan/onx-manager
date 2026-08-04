from __future__ import annotations

from sqlalchemy import Column, DateTime, String, Text

from app.core.persistence.base import Base, TimestampMixin


class PluginModel(Base, TimestampMixin):
    __tablename__ = "plugins"

    id = Column(String(36), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    version = Column(String(32), nullable=False)
    description = Column(Text, nullable=False, default="")
    author = Column(String(128), nullable=False, default="")
    website = Column(String(512), nullable=False, default="")
    dependencies = Column(Text, nullable=False, default="")
    status = Column(String(16), nullable=False, default="installed")
    source = Column(String(16), nullable=False, default="manual")
    external_project_id = Column(String(64), nullable=True)
    external_version_id = Column(String(64), nullable=True)
    external_url = Column(String(512), nullable=True)
    checksum = Column(String(128), nullable=True)
    installed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
