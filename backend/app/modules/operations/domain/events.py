from __future__ import annotations

import time
from typing import Any

from pydantic import Field

from app.core.event_bus import DomainEvent


class OperationStartedEvent(DomainEvent):
    event_type: str = "OperationStartedEvent"
    operation_id: str
    event_seq: int
    type: str
    target_type: str
    target_id: str | None = None
    server_id: str | None = None
    actor_id: str | None = None
    created_at: float = Field(default_factory=time.time)


class OperationStepEvent(DomainEvent):
    event_type: str = "OperationStepEvent"
    operation_id: str
    event_seq: int
    server_id: str | None = None
    step_id: str
    sequence: int
    status: str
    progress: float | None = None
    elapsed_ms: int = 0
    message_key: str | None = None
    safe_to_retry: bool = False
    context: dict[str, Any] = Field(default_factory=dict)


class OperationLogEvent(DomainEvent):
    event_type: str = "OperationLogEvent"
    operation_id: str
    event_seq: int
    server_id: str | None = None
    step_id: str | None = None
    level: str = "info"
    message: str
    timestamp: float = Field(default_factory=time.time)


class OperationCompletedEvent(DomainEvent):
    event_type: str = "OperationCompletedEvent"
    operation_id: str
    event_seq: int
    target_type: str
    target_id: str | None = None
    server_id: str | None = None
    type: str
    elapsed_ms: int = 0
    finished_at: float = Field(default_factory=time.time)


class OperationFailedEvent(DomainEvent):
    event_type: str = "OperationFailedEvent"
    operation_id: str
    event_seq: int
    target_type: str
    target_id: str | None = None
    server_id: str | None = None
    type: str
    failure_code: str
    error_message: str
    failed_step_id: str | None = None
    elapsed_ms: int = 0
    finished_at: float = Field(default_factory=time.time)


class OperationCancelledEvent(DomainEvent):
    event_type: str = "OperationCancelledEvent"
    operation_id: str
    event_seq: int
    target_type: str
    target_id: str | None = None
    server_id: str | None = None
    type: str
    elapsed_ms: int = 0
    finished_at: float = Field(default_factory=time.time)
