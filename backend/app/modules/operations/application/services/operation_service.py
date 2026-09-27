from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.operations.application.services.executor import OperationExecutor
from app.modules.operations.domain.aggregate import Operation
from app.modules.operations.domain.entities import OperationStep
from app.modules.operations.domain.enums import OperationStatus
from app.modules.operations.domain.events import (
    OperationCancelledEvent,
    OperationCompletedEvent,
    OperationFailedEvent,
    OperationLogEvent,
    OperationStartedEvent,
    OperationStepEvent,
)
from app.modules.operations.domain.exceptions import (
    OperationConcurrencyConflictError,
    OperationNotFoundError,
    OperationTerminalConflictError,
)
from app.modules.operations.infrastructure.repository import SQLOperationRepository

logger = logging.getLogger(__name__)

# Mutating live server operations that require exclusive access per server (§15.1)
LIVE_MUTATING_TYPES = {
    "START_SERVER",
    "STOP_SERVER",
    "RESTART_SERVER",
    "DELETE_SERVER",
    "BACKUP_RESTORE",
    "UPDATE_SERVER",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OperationService:
    def __init__(
        self,
        event_bus: EventBus | None = None,
        executor: OperationExecutor | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._executor = executor or OperationExecutor(event_bus)

    @property
    def executor(self) -> OperationExecutor:
        return self._executor

    async def create_operation(
        self,
        type: str,
        target_type: str = "server",
        target_id: str | None = None,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        timeout_seconds: int = 600,
        metadata: dict[str, Any] | None = None,
        initial_steps: list[dict[str, Any]] | None = None,
        session: AsyncSession | None = None,
    ) -> Operation:
        if session is not None:
            return await self._create_operation_with_session(
                session,
                type,
                target_type,
                target_id,
                actor_id,
                idempotency_key,
                timeout_seconds,
                metadata,
                initial_steps,
            )
        async with database.session_factory() as sess:
            op = await self._create_operation_with_session(
                sess,
                type,
                target_type,
                target_id,
                actor_id,
                idempotency_key,
                timeout_seconds,
                metadata,
                initial_steps,
            )
            await sess.commit()
            return op

    async def _create_operation_with_session(
        self,
        session: AsyncSession,
        type: str,
        target_type: str,
        target_id: str | None,
        actor_id: str | None,
        idempotency_key: str | None,
        timeout_seconds: int,
        metadata: dict[str, Any] | None,
        initial_steps: list[dict[str, Any]] | None,
    ) -> Operation:
        repo = SQLOperationRepository(session)

        # 1. Idempotency Check (Layer 2)
        if idempotency_key:
            existing = await repo.get_by_idempotency_key(
                target_type, target_id, idempotency_key
            )
            if existing is not None:
                if existing.is_active or existing.status == OperationStatus.COMPLETED:
                    return existing
                raise OperationConcurrencyConflictError(
                    target_id=target_id or "",
                    op_type=type,
                    message=(
                        f"Operation with idempotency key '{idempotency_key}' "
                        f"already exists in terminal state '{existing.status.value}'"
                    ),
                )

        # 2. Per-target Concurrency Guard (§15.1)
        # RUN_TEST is explicitly exempt from mutual exclusion
        if type in LIVE_MUTATING_TYPES and target_type == "server" and target_id:
            active_ops = await repo.get_active_for_target(target_type, target_id)
            # Filter out RUN_TEST operations if any
            blocking_ops = [op for op in active_ops if op.type != "RUN_TEST"]
            if blocking_ops:
                raise OperationConcurrencyConflictError(
                    target_id=target_id,
                    op_type=type,
                    message=(
                        f"Mutating operation '{blocking_ops[0].type}' is already active "
                        f"on server '{target_id}'"
                    ),
                )

        # 3. Create aggregate and steps
        op = Operation.create(
            type=type,
            target_type=target_type,
            target_id=target_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            timeout_seconds=timeout_seconds,
            metadata=metadata,
        )

        if initial_steps:
            for s_data in initial_steps:
                op.add_step(
                    step_id=s_data["step_id"],
                    sequence=s_data.get("sequence"),
                    message_key=s_data.get("message_key"),
                    safe_to_retry=s_data.get("safe_to_retry", False),
                    context=s_data.get("context"),
                )

        op.next_event_seq()
        saved = await repo.save(op)

        # 4. Emit started event
        if self._event_bus:
            evt = OperationStartedEvent(
                operation_id=saved.id,
                event_seq=saved.last_event_seq,
                type=saved.type,
                target_type=saved.target_type,
                target_id=saved.target_id,
                server_id=saved.target_id if saved.target_type == "server" else None,
                actor_id=saved.actor_id,
            )
            await self._event_bus.publish(evt)

        return saved

    async def get_operation(
        self,
        operation_id: str,
        session: AsyncSession | None = None,
    ) -> Operation:
        if session is not None:
            repo = SQLOperationRepository(session)
            op = await repo.get(operation_id)
            if op is None:
                raise OperationNotFoundError(operation_id)
            return op

        async with database.session_factory() as sess:
            repo = SQLOperationRepository(sess)
            op = await repo.get(operation_id)
            if op is None:
                raise OperationNotFoundError(operation_id)
            return op

    async def list_operations(
        self,
        target_type: str | None = None,
        target_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        session: AsyncSession | None = None,
    ) -> list[Operation]:
        if session is not None:
            repo = SQLOperationRepository(session)
            return await repo.list_operations(target_type, target_id, status, limit)

        async with database.session_factory() as sess:
            repo = SQLOperationRepository(sess)
            return await repo.list_operations(target_type, target_id, status, limit)

    async def request_cancellation(
        self,
        operation_id: str,
        session: AsyncSession | None = None,
    ) -> Operation:
        if session is not None:
            return await self._request_cancellation_with_session(session, operation_id)
        async with database.session_factory() as sess:
            op = await self._request_cancellation_with_session(sess, operation_id)
            await sess.commit()
            return op

    async def _request_cancellation_with_session(
        self,
        session: AsyncSession,
        operation_id: str,
    ) -> Operation:
        repo = SQLOperationRepository(session)
        won = await repo.atomic_request_cancellation(operation_id)
        op = await repo.get(operation_id)
        if op is None:
            raise OperationNotFoundError(operation_id)

        if won:
            cancelled = self._executor.cancel_task(operation_id)
            if not cancelled:
                # If no task was actively running, conclude cancellation immediately
                op.cancel()
                op.next_event_seq()
                op = await repo.save(op)

            if self._event_bus:
                evt = OperationCancelledEvent(
                    operation_id=op.id,
                    event_seq=op.last_event_seq,
                    target_type=op.target_type,
                    target_id=op.target_id,
                    server_id=op.target_id if op.target_type == "server" else None,
                    type=op.type,
                    elapsed_ms=op.elapsed_ms,
                )
                await self._event_bus.publish(evt)
            return op

        # Lost the race or already terminal
        if op.status in (
            OperationStatus.COMPLETED,
            OperationStatus.FAILED,
            OperationStatus.TIMED_OUT,
        ):
            raise OperationTerminalConflictError(
                operation_id, op.status.value, action="cancel"
            )

        # Already CANCEL_REQUESTED or CANCELLED -> return idempotent
        return op

    async def confirm_cancellation(
        self,
        operation_id: str,
        session: AsyncSession | None = None,
    ) -> Operation:
        """Worker completion of the cooperative cancellation path (Stage A §5.4).

        Called by the operation worker after it observes task cancellation and
        finishes cleanup. Transitions CANCEL_REQUESTED -> CANCELLED and emits
        ``OperationCancelledEvent``. If a timeout (or completion) already
        committed a terminal state first, the operation is returned untouched
        so the race winner is never overwritten.
        """
        if session is not None:
            return await self._confirm_cancellation_with_session(session, operation_id)
        async with database.session_factory() as sess:
            op = await self._confirm_cancellation_with_session(sess, operation_id)
            await sess.commit()
            return op

    async def _confirm_cancellation_with_session(
        self,
        session: AsyncSession,
        operation_id: str,
    ) -> Operation:
        repo = SQLOperationRepository(session)
        op = await repo.get(operation_id)
        if op is None:
            raise OperationNotFoundError(operation_id)

        if op.status == OperationStatus.CANCELLED:
            return op
        if op.status != OperationStatus.CANCEL_REQUESTED and not op.cancellation_requested:
            # Timeout, completion, or failure won the race: leave it intact.
            return op

        op.cancel()
        op.next_event_seq()
        saved = await repo.save(op)

        if self._event_bus:
            evt = OperationCancelledEvent(
                operation_id=saved.id,
                event_seq=saved.last_event_seq,
                target_type=saved.target_type,
                target_id=saved.target_id,
                server_id=saved.target_id if saved.target_type == "server" else None,
                type=saved.type,
                elapsed_ms=saved.elapsed_ms,
            )
            await self._event_bus.publish(evt)

        return saved

    async def retry_operation(
        self,
        operation_id: str,
        session: AsyncSession | None = None,
    ) -> Operation:
        if session is not None:
            return await self._retry_operation_with_session(session, operation_id)
        async with database.session_factory() as sess:
            op = await self._retry_operation_with_session(sess, operation_id)
            await sess.commit()
            return op

    async def _retry_operation_with_session(
        self,
        session: AsyncSession,
        operation_id: str,
    ) -> Operation:
        repo = SQLOperationRepository(session)
        op = await repo.get(operation_id)
        if op is None:
            raise OperationNotFoundError(operation_id)

        op.retry()
        op.next_event_seq()
        saved = await repo.save(op)

        if self._event_bus:
            evt = OperationStartedEvent(
                operation_id=saved.id,
                event_seq=saved.last_event_seq,
                type=saved.type,
                target_type=saved.target_type,
                target_id=saved.target_id,
                server_id=saved.target_id if saved.target_type == "server" else None,
                actor_id=saved.actor_id,
            )
            await self._event_bus.publish(evt)

        return saved

    async def start_step(
        self,
        operation_id: str,
        step_id: str,
        at: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> OperationStep:
        if session is not None:
            return await self._start_step_with_session(session, operation_id, step_id, at)
        async with database.session_factory() as sess:
            step = await self._start_step_with_session(sess, operation_id, step_id, at)
            await sess.commit()
            return step

    async def _start_step_with_session(
        self,
        session: AsyncSession,
        operation_id: str,
        step_id: str,
        at: datetime | None,
    ) -> OperationStep:
        repo = SQLOperationRepository(session)
        op = await repo.get(operation_id)
        if op is None:
            raise OperationNotFoundError(operation_id)

        if op.status == OperationStatus.QUEUED:
            op.prepare()
        if op.status == OperationStatus.PREPARING:
            op.start(at=at)

        step = op.start_step(step_id, at=at)
        op.next_event_seq()
        await repo.save(op)

        if self._event_bus:
            evt = OperationStepEvent(
                operation_id=op.id,
                event_seq=op.last_event_seq,
                server_id=op.target_id if op.target_type == "server" else None,
                step_id=step.step_id,
                sequence=step.sequence,
                status=step.status.value,
                progress=step.progress,
                elapsed_ms=step.elapsed_ms,
                message_key=step.message_key,
                safe_to_retry=step.safe_to_retry,
                context=step.context,
            )
            await self._event_bus.publish(evt)

        return step

    async def record_step_progress(
        self,
        operation_id: str,
        step_id: str,
        progress: float | None,
        context: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
    ) -> OperationStep:
        if session is not None:
            return await self._record_step_progress_with_session(
                session, operation_id, step_id, progress, context
            )
        async with database.session_factory() as sess:
            step = await self._record_step_progress_with_session(
                sess, operation_id, step_id, progress, context
            )
            await sess.commit()
            return step

    async def _record_step_progress_with_session(
        self,
        session: AsyncSession,
        operation_id: str,
        step_id: str,
        progress: float | None,
        context: dict[str, Any] | None,
    ) -> OperationStep:
        repo = SQLOperationRepository(session)
        op = await repo.get(operation_id)
        if op is None:
            raise OperationNotFoundError(operation_id)

        step = op.update_step_progress(step_id, progress, context=context)
        op.next_event_seq()
        await repo.save(op)

        if self._event_bus:
            evt = OperationStepEvent(
                operation_id=op.id,
                event_seq=op.last_event_seq,
                server_id=op.target_id if op.target_type == "server" else None,
                step_id=step.step_id,
                sequence=step.sequence,
                status=step.status.value,
                progress=step.progress,
                elapsed_ms=step.elapsed_ms,
                message_key=step.message_key,
                safe_to_retry=step.safe_to_retry,
                context=step.context,
            )
            await self._event_bus.publish(evt)

        return step

    async def complete_step(
        self,
        operation_id: str,
        step_id: str,
        at: datetime | None = None,
        context: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
    ) -> OperationStep:
        if session is not None:
            return await self._complete_step_with_session(
                session, operation_id, step_id, at, context
            )
        async with database.session_factory() as sess:
            step = await self._complete_step_with_session(
                sess, operation_id, step_id, at, context
            )
            await sess.commit()
            return step

    async def _complete_step_with_session(
        self,
        session: AsyncSession,
        operation_id: str,
        step_id: str,
        at: datetime | None,
        context: dict[str, Any] | None,
    ) -> OperationStep:
        repo = SQLOperationRepository(session)
        op = await repo.get(operation_id)
        if op is None:
            raise OperationNotFoundError(operation_id)

        step = op.complete_step(step_id, at=at, context=context)
        op.next_event_seq()
        await repo.save(op)

        if self._event_bus:
            evt = OperationStepEvent(
                operation_id=op.id,
                event_seq=op.last_event_seq,
                server_id=op.target_id if op.target_type == "server" else None,
                step_id=step.step_id,
                sequence=step.sequence,
                status=step.status.value,
                progress=step.progress,
                elapsed_ms=step.elapsed_ms,
                message_key=step.message_key,
                safe_to_retry=step.safe_to_retry,
                context=step.context,
            )
            await self._event_bus.publish(evt)

        return step

    async def fail_step(
        self,
        operation_id: str,
        step_id: str,
        safe_to_retry: bool = False,
        error: str | None = None,
        at: datetime | None = None,
        context: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
    ) -> OperationStep:
        if session is not None:
            return await self._fail_step_with_session(
                session, operation_id, step_id, safe_to_retry, error, at, context
            )
        async with database.session_factory() as sess:
            step = await self._fail_step_with_session(
                sess, operation_id, step_id, safe_to_retry, error, at, context
            )
            await sess.commit()
            return step

    async def _fail_step_with_session(
        self,
        session: AsyncSession,
        operation_id: str,
        step_id: str,
        safe_to_retry: bool,
        error: str | None,
        at: datetime | None,
        context: dict[str, Any] | None,
    ) -> OperationStep:
        repo = SQLOperationRepository(session)
        op = await repo.get(operation_id)
        if op is None:
            raise OperationNotFoundError(operation_id)

        step = op.fail_step(
            step_id, safe_to_retry=safe_to_retry, error=error, at=at, context=context
        )
        op.next_event_seq()
        await repo.save(op)

        if self._event_bus:
            evt = OperationStepEvent(
                operation_id=op.id,
                event_seq=op.last_event_seq,
                server_id=op.target_id if op.target_type == "server" else None,
                step_id=step.step_id,
                sequence=step.sequence,
                status=step.status.value,
                progress=step.progress,
                elapsed_ms=step.elapsed_ms,
                message_key=step.message_key,
                safe_to_retry=step.safe_to_retry,
                context=step.context,
            )
            await self._event_bus.publish(evt)

        return step

    async def complete_operation(
        self,
        operation_id: str,
        at: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> Operation:
        if session is not None:
            return await self._complete_operation_with_session(session, operation_id, at)
        async with database.session_factory() as sess:
            op = await self._complete_operation_with_session(sess, operation_id, at)
            await sess.commit()
            return op

    async def _complete_operation_with_session(
        self,
        session: AsyncSession,
        operation_id: str,
        at: datetime | None,
    ) -> Operation:
        repo = SQLOperationRepository(session)
        op = await repo.get(operation_id)
        if op is None:
            raise OperationNotFoundError(operation_id)

        op.complete(at=at)
        op.next_event_seq()
        saved = await repo.save(op)

        if self._event_bus:
            evt = OperationCompletedEvent(
                operation_id=saved.id,
                event_seq=saved.last_event_seq,
                target_type=saved.target_type,
                target_id=saved.target_id,
                server_id=saved.target_id if saved.target_type == "server" else None,
                type=saved.type,
                elapsed_ms=saved.elapsed_ms,
            )
            await self._event_bus.publish(evt)

        return saved

    async def fail_operation(
        self,
        operation_id: str,
        failure_code: str,
        error_message: str = "",
        failed_step_id: str | None = None,
        at: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> Operation:
        if session is not None:
            return await self._fail_operation_with_session(
                session, operation_id, failure_code, error_message, failed_step_id, at
            )
        async with database.session_factory() as sess:
            op = await self._fail_operation_with_session(
                sess, operation_id, failure_code, error_message, failed_step_id, at
            )
            await sess.commit()
            return op

    async def _fail_operation_with_session(
        self,
        session: AsyncSession,
        operation_id: str,
        failure_code: str,
        error_message: str,
        failed_step_id: str | None,
        at: datetime | None,
    ) -> Operation:
        repo = SQLOperationRepository(session)
        op = await repo.get(operation_id)
        if op is None:
            raise OperationNotFoundError(operation_id)

        op.fail(
            failure_code=failure_code,
            error_message=error_message,
            failed_step_id=failed_step_id,
            at=at,
        )
        op.next_event_seq()
        saved = await repo.save(op)

        if self._event_bus:
            evt = OperationFailedEvent(
                operation_id=saved.id,
                event_seq=saved.last_event_seq,
                target_type=saved.target_type,
                target_id=saved.target_id,
                server_id=saved.target_id if saved.target_type == "server" else None,
                type=saved.type,
                failure_code=saved.failure_code or failure_code,
                error_message=saved.error_message or error_message,
                failed_step_id=failed_step_id or saved.current_step_id,
                elapsed_ms=saved.elapsed_ms,
            )
            await self._event_bus.publish(evt)

        return saved

    async def emit_log(
        self,
        operation_id: str,
        message: str,
        level: str = "info",
        step_id: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        op = await self.get_operation(operation_id, session=session)
        op.next_event_seq()
        if session is not None:
            repo = SQLOperationRepository(session)
            await repo.save(op)
        else:
            async with database.session_factory() as sess:
                repo = SQLOperationRepository(sess)
                await repo.save(op)
                await sess.commit()

        if self._event_bus:
            evt = OperationLogEvent(
                operation_id=op.id,
                event_seq=op.last_event_seq,
                server_id=op.target_id if op.target_type == "server" else None,
                step_id=step_id,
                level=level,
                message=message,
            )
            await self._event_bus.publish(evt)


_global_operation_service: OperationService | None = None


def get_operation_service(
    event_bus: EventBus | None = None,
    executor: OperationExecutor | None = None,
) -> OperationService:
    global _global_operation_service
    if _global_operation_service is None:
        _global_operation_service = OperationService(event_bus=event_bus, executor=executor)
    elif event_bus and _global_operation_service._event_bus is None:
        _global_operation_service._event_bus = event_bus
    return _global_operation_service


def reset_operation_service() -> None:
    global _global_operation_service
    _global_operation_service = None
