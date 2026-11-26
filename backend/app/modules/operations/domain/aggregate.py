from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.operations.domain.entities import OperationStep
from app.modules.operations.domain.enums import OperationStatus, StepStatus
from app.modules.operations.domain.exceptions import (
    InvalidStateTransitionError,
    OperationStepError,
    OperationTerminalConflictError,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_dt(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


@dataclass
class Operation:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = "GENERIC"
    target_type: str = "server"
    target_id: str | None = None
    actor_id: str | None = None
    status: OperationStatus = OperationStatus.QUEUED
    idempotency_key: str | None = None
    current_step_id: str | None = None
    last_event_seq: int = 0
    failure_code: str | None = None
    error_message: str | None = None
    cancellation_requested: bool = False
    timeout_seconds: int = 600
    created_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    steps: list[OperationStep] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        type: str,
        target_type: str,
        target_id: str | None = None,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        timeout_seconds: int = 600,
        metadata: dict[str, Any] | None = None,
        operation_id: str | None = None,
    ) -> Operation:
        return cls(
            id=operation_id or str(uuid.uuid4()),
            type=type,
            target_type=target_type,
            target_id=target_id,
            actor_id=actor_id,
            status=OperationStatus.QUEUED,
            idempotency_key=idempotency_key,
            timeout_seconds=timeout_seconds,
            metadata=metadata or {},
        )

    def next_event_seq(self) -> int:
        self.last_event_seq += 1
        return self.last_event_seq

    @property
    def is_active(self) -> bool:
        return self.status in (
            OperationStatus.QUEUED,
            OperationStatus.PREPARING,
            OperationStatus.RUNNING,
            OperationStatus.CANCEL_REQUESTED,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            OperationStatus.COMPLETED,
            OperationStatus.CANCELLED,
            OperationStatus.FAILED,
            OperationStatus.TIMED_OUT,
        )

    @property
    def elapsed_ms(self) -> int:
        start = _normalize_dt(self.started_at)
        if start is None:
            return 0
        end = _normalize_dt(self.finished_at) or _utcnow()
        return max(0, int((end - start).total_seconds() * 1000))

    def prepare(self) -> None:
        if self.status != OperationStatus.QUEUED:
            raise InvalidStateTransitionError(self.status.value, OperationStatus.PREPARING.value)
        self.status = OperationStatus.PREPARING

    def start(self, at: datetime | None = None) -> None:
        if self.status not in (OperationStatus.QUEUED, OperationStatus.PREPARING):
            raise InvalidStateTransitionError(self.status.value, OperationStatus.RUNNING.value)
        self.status = OperationStatus.RUNNING
        self.started_at = at or _utcnow()

    def request_cancellation(self) -> None:
        if self.is_terminal:
            raise OperationTerminalConflictError(self.id, self.status.value, action="cancel")
        self.cancellation_requested = True
        self.status = OperationStatus.CANCEL_REQUESTED

    def cancel(self, at: datetime | None = None) -> None:
        now = at or _utcnow()
        if self.status != OperationStatus.CANCEL_REQUESTED and not self.cancellation_requested:
            raise InvalidStateTransitionError(self.status.value, OperationStatus.CANCELLED.value)
        self.status = OperationStatus.CANCELLED
        self.finished_at = now
        # Mark active step as cancelled
        for step in self.steps:
            if step.status == StepStatus.IN_PROGRESS:
                step.cancel(at=now)

    def fail(
        self,
        failure_code: str,
        error_message: str = "",
        failed_step_id: str | None = None,
        at: datetime | None = None,
    ) -> None:
        now = _normalize_dt(at) or _utcnow()
        if self.is_terminal:
            raise OperationTerminalConflictError(self.id, self.status.value, action="fail")
        self.status = OperationStatus.FAILED
        self.failure_code = failure_code
        self.error_message = error_message
        self.finished_at = now
        if failed_step_id:
            self.current_step_id = failed_step_id
        for step in self.steps:
            if step.status == StepStatus.IN_PROGRESS:
                step.fail(
                    at=now,
                    context={"error": error_message} if error_message else None,
                )

    def time_out(self, at: datetime | None = None) -> None:
        now = _normalize_dt(at) or _utcnow()
        if self.is_terminal:
            raise OperationTerminalConflictError(self.id, self.status.value, action="timeout")
        self.status = OperationStatus.TIMED_OUT
        self.failure_code = "OPERATION_TIMEOUT"
        self.error_message = f"Operation exceeded timeout of {self.timeout_seconds} seconds"
        self.finished_at = now
        for step in self.steps:
            if step.status == StepStatus.IN_PROGRESS:
                step.fail(at=now, context={"error": self.error_message})

    def complete(self, at: datetime | None = None) -> None:
        now = at or _utcnow()
        if self.status != OperationStatus.RUNNING:
            raise InvalidStateTransitionError(self.status.value, OperationStatus.COMPLETED.value)
        self.status = OperationStatus.COMPLETED
        self.finished_at = now

    def retry(self) -> None:
        if self.status not in (OperationStatus.FAILED, OperationStatus.TIMED_OUT):
            raise InvalidStateTransitionError(
                self.status.value,
                OperationStatus.PREPARING.value,
                reason="Only FAILED or TIMED_OUT operations can be retried",
            )
        failed_step = self.get_step(self.current_step_id) if self.current_step_id else None
        if failed_step and not failed_step.safe_to_retry:
            raise InvalidStateTransitionError(
                self.status.value,
                OperationStatus.PREPARING.value,
                reason="Current failed step is not safe to retry",
            )
        self.status = OperationStatus.PREPARING
        self.failure_code = None
        self.error_message = None
        self.finished_at = None

    def add_step(
        self,
        step_id: str,
        sequence: int | None = None,
        message_key: str | None = None,
        safe_to_retry: bool = False,
        context: dict[str, Any] | None = None,
    ) -> OperationStep:
        seq = sequence if sequence is not None else (len(self.steps) + 1)
        step = OperationStep(
            operation_id=self.id,
            step_id=step_id,
            sequence=seq,
            status=StepStatus.PENDING,
            message_key=message_key,
            safe_to_retry=safe_to_retry,
            context=context or {},
        )
        self.steps.append(step)
        if self.current_step_id is None and seq == 1:
            self.current_step_id = step_id
        return step

    def get_step(self, step_id: str) -> OperationStep | None:
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None

    def start_step(self, step_id: str, at: datetime | None = None) -> OperationStep:
        step = self.get_step(step_id)
        if not step:
            raise OperationStepError(
                step_id, f"Step '{step_id}' does not exist on operation '{self.id}'"
            )
        self.current_step_id = step_id
        step.start(at=at)
        return step

    def update_step_progress(
        self,
        step_id: str,
        progress: float | None,
        context: dict[str, Any] | None = None,
    ) -> OperationStep:
        step = self.get_step(step_id)
        if not step:
            raise OperationStepError(
                step_id, f"Step '{step_id}' does not exist on operation '{self.id}'"
            )
        step.update_progress(progress, context=context)
        return step

    def complete_step(
        self,
        step_id: str,
        at: datetime | None = None,
        context: dict[str, Any] | None = None,
    ) -> OperationStep:
        step = self.get_step(step_id)
        if not step:
            raise OperationStepError(
                step_id, f"Step '{step_id}' does not exist on operation '{self.id}'"
            )
        step.complete(at=at, context=context)
        # Advance current_step_id to next step in sequence if available
        next_seq = step.sequence + 1
        for s in self.steps:
            if s.sequence == next_seq:
                self.current_step_id = s.step_id
                break
        return step

    def fail_step(
        self,
        step_id: str,
        safe_to_retry: bool = False,
        error: str | None = None,
        at: datetime | None = None,
        context: dict[str, Any] | None = None,
    ) -> OperationStep:
        step = self.get_step(step_id)
        if not step:
            raise OperationStepError(
                step_id, f"Step '{step_id}' does not exist on operation '{self.id}'"
            )
        step_ctx = dict(context or {})
        if error:
            step_ctx["error"] = error
        step.fail(safe_to_retry=safe_to_retry, at=at, context=step_ctx)
        self.current_step_id = step_id
        return step
