from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.core.persistence.base import Base, TimestampMixin


class IntegrityAuditModel(Base, TimestampMixin):
    __tablename__ = "integrity_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(String(36), nullable=False, index=True)
    overall_status = Column(String(16), nullable=False)
    scope = Column(String(16), nullable=False, default="full")
    total_checks = Column(Integer, nullable=False, default=0)
    passed_checks = Column(Integer, nullable=False, default=0)
    failed_checks = Column(Integer, nullable=False, default=0)
    warnings = Column(Integer, nullable=False, default=0)
    summary = Column(Text, nullable=True)
    checked_at = Column(DateTime(timezone=True), nullable=False)


class IntegrityBaselineModel(Base, TimestampMixin):
    __tablename__ = "integrity_baseline"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(String(36), nullable=False, index=True)
    file_path = Column(String(1024), nullable=False)
    file_name = Column(String(256), nullable=False)
    file_hash = Column(String(64), nullable=False)
    hash_algorithm = Column(String(16), nullable=False, default="sha256")
    baseline_at = Column(DateTime(timezone=True), nullable=False)


class HealthStatusModel(Base, TimestampMixin):
    __tablename__ = "health_status"

    server_id = Column(String(36), primary_key=True)
    classification = Column(String(16), nullable=False, default="pending")
    previous_classification = Column(String(16), nullable=True)
    contributing_factors = Column(Text, nullable=False, default="[]")
    trend = Column(String(16), nullable=False, default="stable")
    confidence = Column(Float, nullable=False, default=0.0)
    last_updated = Column(DateTime(timezone=True), nullable=False)


class HealthTimelineModel(Base, TimestampMixin):
    __tablename__ = "health_timeline"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(String(36), nullable=False, index=True)
    previous_status = Column(String(16), nullable=True)
    new_status = Column(String(16), nullable=False)
    contributing_factors = Column(Text, nullable=False, default="[]")
    entry_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)


class EvidenceBundleModel(Base, TimestampMixin):
    __tablename__ = "health_evidence"

    id = Column(String(36), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    latest_log_tail = Column(Text, nullable=True)
    crash_reports = Column(Text, nullable=True)
    provider_diagnostics = Column(Text, nullable=True)
    system_snapshot = Column(Text, nullable=True)
    collection_errors = Column(Text, nullable=True)
    recorded_at = Column(DateTime(timezone=True), nullable=False)


class DiagnosticsReportModel(Base, TimestampMixin):
    __tablename__ = "health_diagnostics"

    id = Column(String(36), primary_key=True)
    server_id = Column(String(36), nullable=False, index=True)
    evidence_id = Column(String(36), nullable=True)
    failure_code = Column(String(48), nullable=True)
    confidence = Column(Float, nullable=True)
    summary = Column(Text, nullable=True)
    suggested_action = Column(Text, nullable=True)
    recorded_at = Column(DateTime(timezone=True), nullable=False)
