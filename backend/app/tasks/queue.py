from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text
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
        now = datetime.now(timezone.utc)
        delay_until = None
        if delay > 0:
            delay_until = datetime.fromtimestamp(time.time() + delay, tz=timezone.utc)

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
            model.started_at = datetime.now(timezone.utc)
            await session.commit()

        try:
            result = await handler(params)
            async with await self._session_factory() as session:
                model = await session.get(TaskModel, task_id)
                if model is None:
                    return
                model.status = TaskStatus.SUCCESS
                model.result_json = json.dumps(result) if result is not None else None
                model.completed_at = datetime.now(timezone.utc)
                await session.commit()
        except Exception as e:
            async with await self._session_factory() as session:
                model = await session.get(TaskModel, task_id)
                if model is None:
                    return
                model.status = TaskStatus.FAILED
                model.error = f"{type(e).__name__}: {e}"
                model.completed_at = datetime.now(timezone.utc)
                await session.commit()
