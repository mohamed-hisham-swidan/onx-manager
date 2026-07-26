from __future__ import annotations

from sqlalchemy import Column, DateTime, String, Text

from app.storage.base import Base, TimestampMixin


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
    installed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)
