from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.operations.domain.aggregate import Operation
from app.modules.operations.domain.entities import OperationStep
from app.modules.operations.domain.enums import OperationStatus, StepStatus
from app.modules.operations.domain.repository import OperationRepository
from app.modules.operations.infrastructure.models import OperationModel, OperationStepModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class SQLOperationRepository(OperationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, operation: Operation) -> Operation:
        stmt = (
            select(OperationModel)
            .where(OperationModel.id == operation.id)
            .options(selectinload(OperationModel.steps))
        )
        res = await self._session.execute(stmt)
        model = res.scalar_one_or_none()

        if model is None:
            model = OperationModel(
                id=operation.id,
                type=operation.type,
                target_type=operation.target_type,
                target_id=operation.target_id,
                actor_id=operation.actor_id,
                status=operation.status.value,
                idempotency_key=operation.idempotency_key,
                current_step_id=operation.current_step_id,
                last_event_seq=operation.last_event_seq,
                failure_code=operation.failure_code,
                error_message=operation.error_message,
                cancellation_requested=operation.cancellation_requested,
                timeout_seconds=operation.timeout_seconds,
                created_at=operation.created_at,
                started_at=operation.started_at,
                finished_at=operation.finished_at,
                metadata_json=operation.metadata,
            )
            for step in operation.steps:
                step_model = OperationStepModel(
                    id=step.id,
                    operation_id=operation.id,
                    step_id=step.step_id,
                    sequence=step.sequence,
                    status=step.status.value,
                    progress=step.progress,
                    elapsed_ms=step.elapsed_ms,
                    message_key=step.message_key,
                    safe_to_retry=step.safe_to_retry,
                    context_json=step.context,
                    started_at=step.started_at,
                    completed_at=step.completed_at,
                )
                model.steps.append(step_model)
            self._session.add(model)
        else:
            model.type = operation.type
            model.target_type = operation.target_type
            model.target_id = operation.target_id
            model.actor_id = operation.actor_id
            model.status = operation.status.value
            model.idempotency_key = operation.idempotency_key
            model.current_step_id = operation.current_step_id
            model.last_event_seq = operation.last_event_seq
            model.failure_code = operation.failure_code
            model.error_message = operation.error_message
            model.cancellation_requested = operation.cancellation_requested
            model.timeout_seconds = operation.timeout_seconds
            model.started_at = operation.started_at
            model.finished_at = operation.finished_at
            model.metadata_json = operation.metadata

            existing_steps = {s.step_id: s for s in model.steps}
            current_step_ids = {s.step_id for s in operation.steps}

            # Remove orphaned steps
            model.steps = [s for s in model.steps if s.step_id in current_step_ids]

            for step in operation.steps:
                if step.step_id in existing_steps:
                    sm = existing_steps[step.step_id]
                    sm.sequence = step.sequence
                    sm.status = step.status.value
                    sm.progress = step.progress
                    sm.elapsed_ms = step.elapsed_ms
                    sm.message_key = step.message_key
                    sm.safe_to_retry = step.safe_to_retry
                    sm.context_json = step.context
                    sm.started_at = step.started_at
                    sm.completed_at = step.completed_at
                else:
                    sm = OperationStepModel(
                        id=step.id,
                        operation_id=operation.id,
                        step_id=step.step_id,
                        sequence=step.sequence,
                        status=step.status.value,
                        progress=step.progress,
                        elapsed_ms=step.elapsed_ms,
                        message_key=step.message_key,
                        safe_to_retry=step.safe_to_retry,
                        context_json=step.context,
                        started_at=step.started_at,
                        completed_at=step.completed_at,
                    )
                    model.steps.append(sm)

        await self._session.flush()
        saved = await self.get(operation.id)
        if saved is None:
            return operation
        return saved

    async def get(self, operation_id: str) -> Operation | None:
        stmt = (
            select(OperationModel)
            .where(OperationModel.id == operation_id)
            .options(selectinload(OperationModel.steps))
        )
        res = await self._session.execute(stmt)
        model = res.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def get_by_idempotency_key(
        self,
        target_type: str,
        target_id: str | None,
        idempotency_key: str,
    ) -> Operation | None:
        stmt = select(OperationModel).options(selectinload(OperationModel.steps))
        if target_id is None:
            stmt = stmt.where(
                OperationModel.target_type == target_type,
                OperationModel.target_id.is_(None),
                OperationModel.idempotency_key == idempotency_key,
            )
        else:
            stmt = stmt.where(
                OperationModel.target_type == target_type,
                OperationModel.target_id == target_id,
                OperationModel.idempotency_key == idempotency_key,
            )
        res = await self._session.execute(stmt)
        model = res.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def get_active_for_target(
        self,
        target_type: str,
        target_id: str,
    ) -> list[Operation]:
        active_statuses = [
            OperationStatus.QUEUED.value,
            OperationStatus.PREPARING.value,
            OperationStatus.RUNNING.value,
            OperationStatus.CANCEL_REQUESTED.value,
        ]
        stmt = (
            select(OperationModel)
            .where(
                OperationModel.target_type == target_type,
                OperationModel.target_id == target_id,
                OperationModel.status.in_(active_statuses),
            )
            .options(selectinload(OperationModel.steps))
            .order_by(desc(OperationModel.created_at))
        )
        res = await self._session.execute(stmt)
        models = res.scalars().all()
        return [self._to_domain(m) for m in models]

    async def list_operations(
        self,
        target_type: str | None = None,
        target_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Operation]:
        stmt = select(OperationModel).options(selectinload(OperationModel.steps))
        if target_type:
            stmt = stmt.where(OperationModel.target_type == target_type)
        if target_id:
            stmt = stmt.where(OperationModel.target_id == target_id)
        if status:
            stmt = stmt.where(OperationModel.status == status)
        stmt = stmt.order_by(desc(OperationModel.created_at)).limit(limit)
        res = await self._session.execute(stmt)
        models = res.scalars().all()
        return [self._to_domain(m) for m in models]

    async def atomic_request_cancellation(self, operation_id: str) -> bool:
        stmt = (
            update(OperationModel)
            .where(
                OperationModel.id == operation_id,
                OperationModel.status.in_(
                    [
                        OperationStatus.QUEUED.value,
                        OperationStatus.PREPARING.value,
                        OperationStatus.RUNNING.value,
                    ]
                ),
            )
            .values(
                status=OperationStatus.CANCEL_REQUESTED.value,
                cancellation_requested=True,
            )
        )
        res = await self._session.execute(stmt)
        await self._session.flush()
        return res.rowcount > 0

    async def atomic_timeout(self, operation_id: str) -> bool:
        now = _utcnow()
        stmt = (
            update(OperationModel)
            .where(
                OperationModel.id == operation_id,
                OperationModel.status.in_(
                    [
                        OperationStatus.PREPARING.value,
                        OperationStatus.RUNNING.value,
                    ]
                ),
                OperationModel.cancellation_requested.is_(False),
            )
            .values(
                status=OperationStatus.TIMED_OUT.value,
                failure_code="OPERATION_TIMEOUT",
                error_message="Operation exceeded configured timeout limit",
                finished_at=now,
            )
        )
        res = await self._session.execute(stmt)
        await self._session.flush()
        return res.rowcount > 0

    def _to_domain(self, model: OperationModel) -> Operation:
        steps = [self._step_to_domain(sm) for sm in sorted(model.steps, key=lambda s: s.sequence)]
        return Operation(
            id=model.id,
            type=model.type,
            target_type=model.target_type,
            target_id=model.target_id,
            actor_id=model.actor_id,
            status=OperationStatus(model.status),
            idempotency_key=model.idempotency_key,
            current_step_id=model.current_step_id,
            last_event_seq=model.last_event_seq,
            failure_code=model.failure_code,
            error_message=model.error_message,
            cancellation_requested=model.cancellation_requested,
            timeout_seconds=model.timeout_seconds,
            created_at=_ensure_utc(model.created_at),
            started_at=_ensure_utc(model.started_at),
            finished_at=_ensure_utc(model.finished_at),
            metadata=dict(model.metadata_json) if model.metadata_json else {},
            steps=steps,
        )

    def _step_to_domain(self, model: OperationStepModel) -> OperationStep:
        return OperationStep(
            id=model.id,
            operation_id=model.operation_id,
            step_id=model.step_id,
            sequence=model.sequence,
            status=StepStatus(model.status),
            progress=model.progress,
            elapsed_ms=model.elapsed_ms,
            message_key=model.message_key,
            safe_to_retry=model.safe_to_retry,
            context=dict(model.context_json) if model.context_json else {},
            started_at=_ensure_utc(model.started_at),
            completed_at=_ensure_utc(model.completed_at),
        )
