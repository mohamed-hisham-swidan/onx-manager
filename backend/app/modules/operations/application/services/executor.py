from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.operations.domain.enums import OperationStatus
from app.modules.operations.domain.events import OperationFailedEvent
from app.modules.operations.infrastructure.models import OperationModel

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OperationExecutor:
    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._running_tasks: dict[str, asyncio.Task[Any]] = {}
        self._event_bus = event_bus

    def register_task(self, operation_id: str, task: asyncio.Task[Any]) -> None:
        self._running_tasks[operation_id] = task

        def _cleanup(_task: asyncio.Task[Any]) -> None:
            self._running_tasks.pop(operation_id, None)

        task.add_done_callback(_cleanup)

    def cancel_task(self, operation_id: str) -> bool:
        task = self._running_tasks.get(operation_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def shutdown(self, grace_seconds: float = 10.0) -> None:
        """Graceful shutdown of running operations during server lifespan shutdown."""
        if not self._running_tasks:
            return

        logger.info(
            "Shutting down OperationExecutor with %d running tasks (grace period %.1fs)",
            len(self._running_tasks),
            grace_seconds,
        )

        tasks = list(self._running_tasks.values())
        op_ids = list(self._running_tasks.keys())

        # Signal cancellation
        for task in tasks:
            if not task.done():
                task.cancel()

        # Wait up to grace_seconds
        done, pending = await asyncio.wait(tasks, timeout=grace_seconds)

        # Mark any remaining running operations as FAILED with SERVER_SHUTDOWN in DB
        async with database.session_factory() as session:
            now = _utcnow()
            for op_id in op_ids:
                stmt = (
                    update(OperationModel)
                    .where(
                        OperationModel.id == op_id,
                        OperationModel.status.in_(
                            [
                                OperationStatus.PREPARING.value,
                                OperationStatus.RUNNING.value,
                                OperationStatus.CANCEL_REQUESTED.value,
                            ]
                        ),
                    )
                    .values(
                        status=OperationStatus.FAILED.value,
                        failure_code="SERVER_SHUTDOWN",
                        error_message="Operation interrupted by server shutdown",
                        finished_at=now,
                    )
                )
                await session.execute(stmt)
            await session.commit()

        self._running_tasks.clear()


class OperationRecoveryReconciler:
    """Startup reconciler for operations interrupted by unexpected process termination."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus

    async def reconcile_on_startup(self) -> None:
        queue_policy = os.environ.get("ONX_OPERATION_STARTUP_QUEUE_POLICY", "PURGE").upper()
        now = _utcnow()

        async with database.session_factory() as session:
            # 1. PREPARING and RUNNING -> FAILED with PROCESS_TERMINATED
            stmt_running = select(OperationModel).where(
                OperationModel.status.in_(
                    [
                        OperationStatus.PREPARING.value,
                        OperationStatus.RUNNING.value,
                        OperationStatus.CANCEL_REQUESTED.value,
                    ]
                )
            )
            res_running = await session.execute(stmt_running)
            interrupted_ops = res_running.scalars().all()

            for op in interrupted_ops:
                op.status = OperationStatus.FAILED.value
                op.failure_code = "PROCESS_TERMINATED"
                op.error_message = (
                    "Operation execution aborted due to unexpected backend termination"
                )
                op.finished_at = now
                op.last_event_seq += 1

                if self._event_bus:
                    evt = OperationFailedEvent(
                        operation_id=op.id,
                        event_seq=op.last_event_seq,
                        target_type=op.target_type,
                        target_id=op.target_id,
                        server_id=op.target_id if op.target_type == "server" else None,
                        type=op.type,
                        failure_code="PROCESS_TERMINATED",
                        error_message=op.error_message,
                    )
                    await self._event_bus.publish(evt)

            # 2. QUEUED operations handling per ONX_OPERATION_STARTUP_QUEUE_POLICY
            if queue_policy == "PURGE":
                stmt_queued = select(OperationModel).where(
                    OperationModel.status == OperationStatus.QUEUED.value
                )
                res_queued = await session.execute(stmt_queued)
                queued_ops = res_queued.scalars().all()

                for op in queued_ops:
                    op.status = OperationStatus.FAILED.value
                    op.failure_code = "QUEUE_PURGED_ON_RESTART"
                    op.error_message = (
                        "Operation was queued when backend restarted and was purged "
                        "per default startup policy"
                    )
                    op.finished_at = now
                    op.last_event_seq += 1

                    if self._event_bus:
                        evt = OperationFailedEvent(
                            operation_id=op.id,
                            event_seq=op.last_event_seq,
                            target_type=op.target_type,
                            target_id=op.target_id,
                            server_id=op.target_id if op.target_type == "server" else None,
                            type=op.type,
                            failure_code="QUEUE_PURGED_ON_RESTART",
                            error_message=op.error_message,
                        )
                        await self._event_bus.publish(evt)

            await session.commit()
