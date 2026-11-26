from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.operations.domain.enums import OperationStatus, StepStatus
from app.modules.operations.domain.events import OperationFailedEvent
from app.modules.operations.infrastructure.models import OperationModel, OperationStepModel

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OperationExecutor:
    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._running_tasks: dict[str, asyncio.Task[Any]] = {}
        self._registered_operation_ids: set[str] = set()
        self._timeout_watchers: dict[str, asyncio.Task[Any]] = {}
        self._event_bus = event_bus

    def register_task(self, operation_id: str, task: asyncio.Task[Any]) -> None:
        self._registered_operation_ids.add(operation_id)
        self._running_tasks[operation_id] = task

        def _cleanup(_task: asyncio.Task[Any]) -> None:
            self._running_tasks.pop(operation_id, None)
            watcher = self._timeout_watchers.pop(operation_id, None)
            if watcher is not None and not watcher.done():
                watcher.cancel()

        task.add_done_callback(_cleanup)

    def has_live_task(self, operation_id: str) -> bool:
        """Return True when the operation has an active, non-done asyncio Task."""
        task = self._running_tasks.get(operation_id)
        return task is not None and not task.done()

    def was_task_registered_and_exited(self, operation_id: str) -> bool:
        """Return True if a task was previously registered in this process and is no longer live."""
        return (
            operation_id in self._registered_operation_ids
            and not self.has_live_task(operation_id)
        )

    def cancel_task(self, operation_id: str) -> bool:
        task = self._running_tasks.get(operation_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def schedule_timeout_watch(
        self, operation_id: str, timeout_seconds: float | None
    ) -> asyncio.Task[Any] | None:
        """Arm the designed per-operation timeout watcher (Stage A §5.4).

        The watcher sleeps for ``timeout_seconds`` then invokes
        :meth:`_handle_timeout`, whose atomic conditional update guarantees
        "first committed transition wins" against a concurrent cancellation.
        The watcher is cancelled automatically when the operation task
        completes (via the ``register_task`` done-callback) or at shutdown.
        """
        if timeout_seconds is None or timeout_seconds <= 0:
            return None
        existing = self._timeout_watchers.get(operation_id)
        if existing is not None and not existing.done():
            return existing
        try:
            watcher = asyncio.get_running_loop().create_task(
                self._timeout_watch(operation_id, float(timeout_seconds))
            )
        except RuntimeError:
            return None
        self._timeout_watchers[operation_id] = watcher

        def _forget(_task: asyncio.Task[Any]) -> None:
            self._timeout_watchers.pop(operation_id, None)

        watcher.add_done_callback(_forget)

        op_task = self._running_tasks.get(operation_id)
        if op_task is not None and op_task is not watcher:

            def _cancel_watcher(_task: asyncio.Task[Any]) -> None:
                w = self._timeout_watchers.pop(operation_id, None)
                if w is not None and not w.done():
                    w.cancel()

            op_task.add_done_callback(_cancel_watcher)
        return watcher

    async def _timeout_watch(self, operation_id: str, timeout_seconds: float) -> None:
        try:
            await asyncio.sleep(timeout_seconds)
        except asyncio.CancelledError:
            return
        try:
            await self._handle_timeout(operation_id)
        except Exception:
            logger.exception("Timeout handling failed for operation %s", operation_id)

    async def _handle_timeout(self, operation_id: str) -> bool:
        """Designed timeout path (Stage A §5.4): atomic TIMED_OUT wins or yields.

        Returns True when this call committed the TIMED_OUT transition,
        False when cancellation/completion won the race (rowcount == 0) or
        when persistence is unavailable.
        """
        from app.modules.operations.infrastructure.repository import SQLOperationRepository

        try:
            session_factory = database.session_factory
        except RuntimeError:
            logger.debug("Database not initialized; skipping timeout for %s", operation_id)
            return False

        try:
            async with session_factory() as session:
                repo = SQLOperationRepository(session)
                won = await repo.atomic_timeout(operation_id)
                op = await repo.get(operation_id)
                if won and op is not None:
                    now = op.finished_at or _utcnow()
                    timeout_err = op.error_message or "Operation exceeded configured timeout limit"
                    for step in op.steps:
                        if step.status == StepStatus.IN_PROGRESS:
                            step.fail(at=now, context={"error": timeout_err})
                    # Keep the per-operation sequence monotonic for the
                    # timeout event published below.
                    op.last_event_seq += 1
                    op = await repo.save(op)
                    if op.type == "SERVER_UPGRADE":
                        upgrade_id = (op.metadata or {}).get("upgrade_id")
                        if upgrade_id:
                            from app.modules.versioning.infrastructure.models import (
                                ServerUpgradeModel,
                            )

                            await session.execute(
                                update(ServerUpgradeModel)
                                .where(
                                    ServerUpgradeModel.id == str(upgrade_id),
                                    ServerUpgradeModel.status == "applying",
                                )
                                .values(
                                    status="failed",
                                    error_code="OPERATION_TIMEOUT",
                                    error_message=timeout_err[:512],
                                    updated_at=now,
                                )
                            )
                await session.commit()
        except Exception:
            logger.exception("Timeout persistence failed for operation %s", operation_id)
            return False

        if not won:
            # Cancellation committed first (or the operation already reached a
            # terminal state): timeout yields, leaving it intact.
            return False

        # Timeout won: cooperatively cancel the running task (if any) so the
        # worker aborts at its next safe boundary, then emit the failure event.
        self.cancel_task(operation_id)
        if self._event_bus and op is not None:
            try:
                evt = OperationFailedEvent(
                    operation_id=op.id,
                    event_seq=op.last_event_seq,
                    target_type=op.target_type,
                    target_id=op.target_id,
                    server_id=op.target_id if op.target_type == "server" else None,
                    type=op.type,
                    failure_code="OPERATION_TIMEOUT",
                    error_message="Operation exceeded configured timeout limit",
                    elapsed_ms=op.elapsed_ms,
                )
                await self._event_bus.publish(evt)
            except Exception:
                logger.exception(
                    "Failed publishing timeout event for operation %s", operation_id
                )
        return True

    async def shutdown(self, grace_seconds: float = 10.0) -> None:
        """Graceful shutdown of running operations during server lifespan shutdown."""
        for watcher in list(self._timeout_watchers.values()):
            if not watcher.done():
                watcher.cancel()
        self._timeout_watchers.clear()

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
                step_stmt = (
                    update(OperationStepModel)
                    .where(
                        OperationStepModel.operation_id == op_id,
                        OperationStepModel.status == StepStatus.IN_PROGRESS.value,
                    )
                    .values(
                        status=StepStatus.FAILED.value,
                        completed_at=now,
                    )
                )
                await session.execute(step_stmt)
            await session.commit()

        self._running_tasks.clear()


class OperationRecoveryReconciler:
    """Startup reconciler for operations interrupted by unexpected process termination."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus

    async def reconcile_on_startup(self) -> None:
        raw_policy = os.environ.get("ONX_OPERATION_STARTUP_QUEUE_POLICY", "PURGE")
        queue_policy = (raw_policy or "PURGE").strip().upper()
        if queue_policy not in ("PURGE", "RE_DISPATCH"):
            logger.warning(
                "Unknown ONX_OPERATION_STARTUP_QUEUE_POLICY=%r — falling back "
                "to the documented safe default PURGE",
                raw_policy,
            )
            queue_policy = "PURGE"
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

            def _close_step_model(
                step_row: OperationStepModel,
                end_dt: datetime,
                reason: str,
            ) -> None:
                step_row.status = StepStatus.FAILED.value
                step_row.completed_at = end_dt
                if step_row.started_at is not None:
                    st = (
                        step_row.started_at
                        if step_row.started_at.tzinfo is not None
                        else step_row.started_at.replace(tzinfo=UTC)
                    )
                    end_utc = (
                        end_dt if end_dt.tzinfo is not None else end_dt.replace(tzinfo=UTC)
                    )
                    step_row.elapsed_ms = max(
                        int(step_row.elapsed_ms or 0),
                        max(0, int((end_utc - st).total_seconds() * 1000)),
                    )
                ctx = dict(step_row.context_json or {})
                ctx.setdefault("error", reason)
                step_row.context_json = ctx

            for op in interrupted_ops:
                op.status = OperationStatus.FAILED.value
                op.failure_code = "PROCESS_TERMINATED"
                op.error_message = (
                    "Operation execution aborted due to unexpected backend termination"
                )
                op.finished_at = now
                op.last_event_seq += 1
                for step_row in op.steps:
                    if step_row.status == StepStatus.IN_PROGRESS.value:
                        _close_step_model(step_row, now, op.error_message)

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

            # 1b. Close any orphaned IN_PROGRESS steps whose parent Operation is already terminal
            terminal_statuses = [
                OperationStatus.COMPLETED.value,
                OperationStatus.FAILED.value,
                OperationStatus.TIMED_OUT.value,
                OperationStatus.CANCELLED.value,
            ]
            stmt_orphaned_steps = (
                select(OperationStepModel, OperationModel)
                .join(OperationModel, OperationStepModel.operation_id == OperationModel.id)
                .where(
                    OperationStepModel.status == StepStatus.IN_PROGRESS.value,
                    OperationModel.status.in_(terminal_statuses),
                )
            )
            orphaned_rows = (await session.execute(stmt_orphaned_steps)).all()
            for step_row, parent_op in orphaned_rows:
                end_dt = parent_op.finished_at or now
                reason = parent_op.error_message or "Operation terminated before step completed"
                _close_step_model(step_row, end_dt, reason)

            # 1c. Reconcile any ServerUpgradeModel rows stranded in 'applying' whose operation
            # is already terminal or missing (never touches running Docker containers).
            try:
                from app.modules.versioning.infrastructure.models import ServerUpgradeModel

                stmt_applying = select(ServerUpgradeModel).where(
                    ServerUpgradeModel.status == "applying"
                )
                applying_upgrades = (await session.execute(stmt_applying)).scalars().all()
                for upg in applying_upgrades:
                    op_is_active = False
                    if upg.operation_id:
                        parent_op = await session.get(OperationModel, str(upg.operation_id))
                        if parent_op is not None and parent_op.status not in terminal_statuses:
                            op_is_active = True
                    if not op_is_active:
                        upg.status = "failed"
                        upg.error_code = upg.error_code or "PROCESS_TERMINATED"
                        upg.error_message = (
                            upg.error_message
                            or "Upgrade was interrupted by backend restart"
                        )
                        upg.updated_at = now
            except Exception:
                logger.exception("Failed reconciling stranded applying server upgrades")

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
            else:
                # RE_DISPATCH: per the approved design (§5.5), QUEUED rows are
                # left untouched for re-dispatch in created_at order. Stage A
                # ships no generic re-execution substrate (only RUN_TEST is
                # operation-wired and its container died with the process), so
                # the reconciler preserves the rows and logs them for an
                # external dispatcher instead of claiming an enqueue it cannot
                # perform. The documented safe default remains PURGE.
                stmt_queued = (
                    select(OperationModel)
                    .where(OperationModel.status == OperationStatus.QUEUED.value)
                    .order_by(OperationModel.created_at)
                )
                res_queued = await session.execute(stmt_queued)
                queued_ops = res_queued.scalars().all()
                if queued_ops:
                    logger.info(
                        "ONX_OPERATION_STARTUP_QUEUE_POLICY=RE_DISPATCH: "
                        "preserving %d QUEUED operation(s) for re-dispatch",
                        len(queued_ops),
                    )

            await session.commit()
