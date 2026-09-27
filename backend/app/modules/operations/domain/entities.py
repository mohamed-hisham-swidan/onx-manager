from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.operations.domain.enums import StepStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_dt(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


@dataclass
class OperationStep:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    operation_id: str = ""
    step_id: str = ""
    sequence: int = 1
    status: StepStatus = StepStatus.PENDING
    progress: float | None = None
    elapsed_ms: int = 0
    message_key: str | None = None
    safe_to_retry: bool = False
    context: dict[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status == StepStatus.IN_PROGRESS

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            StepStatus.COMPLETED,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
            StepStatus.CANCELLED,
        )

    def start(self, at: datetime | None = None) -> None:
        self.status = StepStatus.IN_PROGRESS
        self.started_at = _normalize_dt(at) or _utcnow()

    def update_progress(
        self,
        progress: float | None,
        context: dict[str, Any] | None = None,
    ) -> None:
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        if context:
            self.context.update(context)
        start = _normalize_dt(self.started_at)
        if start is not None:
            now = _utcnow()
            self.elapsed_ms = max(0, int((now - start).total_seconds() * 1000))

    def complete(self, at: datetime | None = None, context: dict[str, Any] | None = None) -> None:
        now = _normalize_dt(at) or _utcnow()
        self.status = StepStatus.COMPLETED
        self.completed_at = now
        start = _normalize_dt(self.started_at)
        if start is not None:
            self.elapsed_ms = max(0, int((now - start).total_seconds() * 1000))
        self.progress = 1.0
        if context:
            self.context.update(context)

    def fail(
        self,
        safe_to_retry: bool = False,
        at: datetime | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        now = at or _utcnow()
        self.status = StepStatus.FAILED
        self.safe_to_retry = safe_to_retry
        self.completed_at = now
        if self.started_at is not None:
            self.elapsed_ms = int((now - self.started_at).total_seconds() * 1000)
        if context:
            self.context.update(context)

    def cancel(self, at: datetime | None = None) -> None:
        now = at or _utcnow()
        self.status = StepStatus.CANCELLED
        self.completed_at = now
        if self.started_at is not None:
            self.elapsed_ms = int((now - self.started_at).total_seconds() * 1000)

    def skip(self) -> None:
        self.status = StepStatus.SKIPPED
