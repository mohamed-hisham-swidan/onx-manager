from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.core.persistence.base import Base, TimestampMixin


class MetricPointModel(Base, TimestampMixin):
    __tablename__ = "metric_points"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(String(36), nullable=False, index=True)
    tps = Column(Float, nullable=False)
    players = Column(Integer, nullable=False, default=0)
    ram_used_mb = Column(Float, nullable=False, default=0)
    cpu_percent = Column(Float, nullable=False, default=0)
    recorded_at = Column(DateTime(timezone=True), nullable=False)


class AlertRuleModel(Base, TimestampMixin):
    __tablename__ = "alert_rules"

    id = Column(String(36), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    metric_name = Column(String(64), nullable=False)
    condition = Column(String(8), nullable=False)
    threshold = Column(Float, nullable=False)
    severity = Column(String(16), nullable=False, default="warning")
    enabled = Column(Boolean, nullable=False, default=True)
    cooldown_minutes = Column(Integer, nullable=False, default=15)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
