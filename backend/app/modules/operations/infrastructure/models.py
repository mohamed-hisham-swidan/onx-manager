from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.persistence.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OperationModel(Base):
    __tablename__ = "operations"

    id = Column(String(36), primary_key=True)
    type = Column(String(64), nullable=False, index=True)
    target_type = Column(String(32), nullable=False)
    target_id = Column(String(36), nullable=True)
    actor_id = Column(String(36), nullable=True)
    status = Column(String(32), nullable=False, default="QUEUED", index=True)
    idempotency_key = Column(String(64), nullable=True)
    current_step_id = Column(String(64), nullable=True)
    last_event_seq = Column(Integer, nullable=False, default=0)
    failure_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    cancellation_requested = Column(Boolean, nullable=False, default=False)
    timeout_seconds = Column(Integer, nullable=False, default=600)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(JSON, nullable=True)

    steps = relationship(
        "OperationStepModel",
        back_populates="operation",
        cascade="all, delete-orphan",
        order_by="OperationStepModel.sequence",
        lazy="selectin",
    )

    __table_args__ = (
        Index("idx_operations_target", "target_type", "target_id"),
        UniqueConstraint(
            "target_type",
            "target_id",
            "idempotency_key",
            name="uq_operations_target_idempotency",
        ),
    )


class OperationStepModel(Base):
    __tablename__ = "operation_steps"

    id = Column(String(36), primary_key=True)
    operation_id = Column(
        String(36),
        ForeignKey("operations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id = Column(String(64), nullable=False)
    sequence = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    progress = Column(Float, nullable=True)
    elapsed_ms = Column(Integer, nullable=False, default=0)
    message_key = Column(String(128), nullable=True)
    safe_to_retry = Column(Boolean, nullable=False, default=False)
    context_json = Column(JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    operation = relationship("OperationModel", back_populates="steps")

    __table_args__ = (
        UniqueConstraint("operation_id", "sequence", name="uq_operation_step_sequence"),
        UniqueConstraint("operation_id", "step_id", name="uq_operation_step_id"),
    )
