from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistence.base import Base
from app.tasks.base import TaskQueue, TaskStatus


class TaskModel(Base):
    __tablename__ = "task_queue"

    task_id = Column(String(36), primary_key=True)
    name = Column(String(128), nullable=False)
    params_json = Column(Text, nullable=False, default="{}")
    status = Column(Integer, nullable=False, default=0)
    result_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    delay_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class InProcessQueue(TaskQueue):
    def __init__(self, session_factory: Callable[[], Coroutine[Any, Any, AsyncSession]]) -> None:
        self._session_factory = session_factory
        self._results: dict[str, Any] = {}
        self._handlers: dict[str, Callable[[dict[str, Any]], Coroutine[Any, Any, Any]]] = {}

    def register(
        self,
        name: str,
        handler: Callable[[dict[str, Any]], Coroutine[Any, Any, Any]],
    ) -> None:
        self._handlers[name] = handler

    async def enqueue(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        delay: int = 0,
    ) -> str:
        task_id = uuid.uuid4().hex
        now = datetime.now(UTC)
        delay_until = None
        if delay > 0:
            delay_until = datetime.fromtimestamp(time.time() + delay, tz=UTC)

        async with await self._session_factory() as session:
            model = TaskModel(
                task_id=task_id,
                name=name,
                params_json=json.dumps(params or {}),
                status=TaskStatus.PENDING,
                delay_until=delay_until,
                created_at=now,
            )
            session.add(model)
            await session.commit()

        if delay == 0 and name in self._handlers:
            asyncio.ensure_future(self._execute(task_id, name, params or {}))

        return task_id

    async def cancel(self, task_id: str) -> bool:
        async with await self._session_factory() as session:
            model = await session.get(TaskModel, task_id)
            if model is None or model.status not in (TaskStatus.PENDING,):
                return False
            model.status = TaskStatus.CANCELLED
            await session.commit()
        return True

    async def get_status(self, task_id: str) -> TaskStatus:
        async with await self._session_factory() as session:
            model = await session.get(TaskModel, task_id)
            if model is None:
                return TaskStatus.FAILED
            return TaskStatus(model.status)

    async def get_result(self, task_id: str) -> Any:
        async with await self._session_factory() as session:
            model = await session.get(TaskModel, task_id)
            if model is None:
                return None
            if model.status == TaskStatus.SUCCESS.value:
                return json.loads(model.result_json) if model.result_json else None
            if model.status == TaskStatus.FAILED.value:
                raise RuntimeError(model.error or "Task failed")
            return None

    async def _execute(self, task_id: str, name: str, params: dict[str, Any]) -> None:
        handler = self._handlers.get(name)
        if handler is None:
            return

        async with await self._session_factory() as session:
            model = await session.get(TaskModel, task_id)
            if model is None:
                return
            model.status = TaskStatus.RUNNING
            model.started_at = datetime.now(UTC)
            await session.commit()

        try:
            result = await handler(params)
            async with await self._session_factory() as session:
                model = await session.get(TaskModel, task_id)
                if model is None:
                    return
                model.status = TaskStatus.SUCCESS
                model.result_json = json.dumps(result) if result is not None else None
                model.completed_at = datetime.now(UTC)
                await session.commit()
        except Exception as e:
            async with await self._session_factory() as session:
                model = await session.get(TaskModel, task_id)
                if model is None:
                    return
                model.status = TaskStatus.FAILED
                model.error = f"{type(e).__name__}: {e}"
                model.completed_at = datetime.now(UTC)
                await session.commit()

    async def reclaim_pending(self) -> dict[str, int]:
        """Re-run PENDING tasks whose handler is registered; report unregistered ones.

        Only PENDING (status=0) rows are touched. Registered tasks are transitioned
        to RUNNING and dispatched through the same ``_execute`` path, reusing the
        existing task_id (no duplicate row). Unregistered tasks are left untouched
        and returned in ``skipped_unregistered`` for the caller to triage.
        """
        async with await self._session_factory() as session:
            stmt = select(TaskModel).where(TaskModel.status == TaskStatus.PENDING)
            result = await session.execute(stmt)
            pending = list(result.scalars().all())

        reclaimed = 0
        skipped_unregistered = 0
        errors = 0
        for model in pending:
            if model.name not in self._handlers:
                skipped_unregistered += 1
                continue
            params = json.loads(model.params_json) if model.params_json else {}
            # Guard against double-run: only claim the row if it is still PENDING.
            async with await self._session_factory() as session:
                stmt = (
                    update(TaskModel)
                    .where(
                        TaskModel.task_id == model.task_id,
                        TaskModel.status == TaskStatus.PENDING,
                    )
                    .values(status=TaskStatus.RUNNING, started_at=datetime.now(UTC))
                )
                claimed = await session.execute(stmt)
                await session.commit()
            if claimed.rowcount != 1:
                continue
            asyncio.ensure_future(self._execute(model.task_id, model.name, params))
            reclaimed += 1

        return {
            "reclaimed": reclaimed,
            "skipped_unregistered": skipped_unregistered,
            "errors": errors,
        }

    async def mark_stale_running_failed(self, max_age_minutes: int = 30) -> int:
        """Mark RUNNING tasks that appear orphaned as FAILED.

        A RUNNING row is stale if it has no started_at (inconsistent) or if it
        started more than ``max_age_minutes`` ago. Only these rows are touched;
        healthy short-running tasks are never affected.
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
        async with await self._session_factory() as session:
            stmt = (
                update(TaskModel)
                .where(
                    TaskModel.status == TaskStatus.RUNNING,
                    or_(
                        TaskModel.started_at.is_(None),
                        TaskModel.started_at < cutoff,
                    ),
                )
                .values(
                    status=TaskStatus.FAILED,
                    error="interrupted by process restart",
                    completed_at=datetime.now(UTC),
                )
            )
            result = await session.execute(stmt)
            await session.commit()
        return result.rowcount or 0


_task_queue: TaskQueue | None = None


def init_task_queue(queue: TaskQueue) -> None:
    global _task_queue
    _task_queue = queue


def get_task_queue() -> TaskQueue:
    if _task_queue is None:
        raise RuntimeError("TaskQueue not initialized")
    return _task_queue
