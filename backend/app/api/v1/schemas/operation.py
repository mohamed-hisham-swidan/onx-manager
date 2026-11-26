from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.api.v1.schemas.common import BaseResponse
from app.core.timeutil import format_datetime_utc
from app.modules.operations.domain.aggregate import Operation
from app.modules.operations.domain.entities import OperationStep
from app.modules.operations.domain.enums import StepStatus


class CreateOperationRequest(BaseModel):
    type: str = Field(..., min_length=1, max_length=64)
    target_type: str = Field(default="server", max_length=32)
    target_id: str | None = None
    idempotency_key: str | None = None
    timeout_seconds: int = Field(default=600, ge=1, le=86400)
    metadata: dict[str, Any] = Field(default_factory=dict)
    initial_steps: list[dict[str, Any]] | None = None


class OperationStepResponse(BaseResponse):
    id: str
    step_id: str
    sequence: int
    status: str
    progress: float | None = None
    elapsed_ms: int = 0
    message_key: str | None = None
    safe_to_retry: bool = False
    context: dict[str, Any] = Field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None

    @classmethod
    def from_domain(
        cls,
        step: OperationStep,
        *,
        parent_terminal: bool = False,
        parent_finished_at: datetime | None = None,
    ) -> OperationStepResponse:
        elapsed = step.elapsed_ms
        if step.started_at is not None:
            start = (
                step.started_at
                if step.started_at.tzinfo is not None
                else step.started_at.replace(tzinfo=UTC)
            )
            if step.status == StepStatus.IN_PROGRESS and not parent_terminal:
                live_ms = max(0, int((datetime.now(UTC) - start).total_seconds() * 1000))
                elapsed = max(elapsed, live_ms)
            elif elapsed <= 0 and (step.completed_at is not None or parent_finished_at is not None):
                end_dt = step.completed_at or parent_finished_at or start
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=UTC)
                elapsed = max(0, int((end_dt - start).total_seconds() * 1000))
        return cls(
            id=step.id,
            step_id=step.step_id,
            sequence=step.sequence,
            status=step.status.value,
            progress=step.progress,
            elapsed_ms=elapsed,
            message_key=step.message_key,
            safe_to_retry=step.safe_to_retry,
            context=step.context,
            started_at=format_datetime_utc(step.started_at) if step.started_at else None,
            completed_at=format_datetime_utc(step.completed_at) if step.completed_at else None,
        )


class OperationSummaryResponse(BaseResponse):
    id: str
    type: str
    target_type: str
    target_id: str | None = None
    actor_id: str | None = None
    status: str
    idempotency_key: str | None = None
    current_step_id: str | None = None
    last_event_seq: int = 0
    failure_code: str | None = None
    error_message: str | None = None
    timeout_seconds: int = 600
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_ms: int = 0

    @classmethod
    def from_domain(cls, op: Operation) -> OperationSummaryResponse:
        return cls(
            id=op.id,
            type=op.type,
            target_type=op.target_type,
            target_id=op.target_id,
            actor_id=op.actor_id,
            status=op.status.value,
            idempotency_key=op.idempotency_key,
            current_step_id=op.current_step_id,
            last_event_seq=op.last_event_seq,
            failure_code=op.failure_code,
            error_message=op.error_message,
            timeout_seconds=op.timeout_seconds,
            created_at=format_datetime_utc(op.created_at) if op.created_at else "",
            started_at=format_datetime_utc(op.started_at) if op.started_at else None,
            finished_at=format_datetime_utc(op.finished_at) if op.finished_at else None,
            elapsed_ms=op.elapsed_ms,
        )


class OperationDetailResponse(OperationSummaryResponse):
    metadata: dict[str, Any] = Field(default_factory=dict)
    steps: list[OperationStepResponse] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, op: Operation) -> OperationDetailResponse:
        summary = OperationSummaryResponse.from_domain(op)
        steps = [
            OperationStepResponse.from_domain(
                s,
                parent_terminal=op.is_terminal,
                parent_finished_at=op.finished_at,
            )
            for s in op.steps
        ]
        return cls(
            **summary.model_dump(),
            metadata=op.metadata,
            steps=steps,
        )
