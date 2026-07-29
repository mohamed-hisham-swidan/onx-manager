from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistence.base import Base
from app.tasks.base import TaskQueue


class CronJobModel(Base):
    __tablename__ = "cron_jobs"

    id = Column(String(36), primary_key=True)
    name = Column(String(128), nullable=False, unique=True)
    cron_expression = Column(String(64), nullable=False)
    task_name = Column(String(128), nullable=False)
    params_json = Column(Text, nullable=False, default="{}")
    enabled = Column(Integer, nullable=False, default=1)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class Scheduler:
    def __init__(self, session_factory: Callable[[], Coroutine[Any, Any, AsyncSession]]) -> None:
        self._session_factory = session_factory
        self._aps: Any = None
        self._task_queue: TaskQueue | None = None
        self._running = False

    def set_task_queue(self, queue: TaskQueue) -> None:
        self._task_queue = queue

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        self._aps = AsyncIOScheduler()

        jobs = await self._load_jobs()
        for job in jobs:
            self._schedule_job(job)

        self._aps.start()

    async def stop(self) -> None:
        if self._aps:
            self._aps.shutdown(wait=False)
        self._running = False

    async def add_job(
        self,
        name: str,
        cron_expression: str,
        task_name: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        job_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)

        async with await self._session_factory() as session:
            model = CronJobModel(
                id=job_id,
                name=name,
                cron_expression=cron_expression,
                task_name=task_name,
                params_json=json.dumps(params or {}),
                enabled=1,
                created_at=now,
            )
            session.add(model)
            await session.commit()

        if self._aps:
            self._schedule_job(model)

    async def remove_job(self, job_id: str) -> bool:
        async with await self._session_factory() as session:
            model = await session.get(CronJobModel, job_id)
            if model is None:
                return False
            await session.delete(model)
            await session.commit()

        if self._aps and self._aps.get_job(job_id):
            self._aps.remove_job(job_id)
        return True

    async def _load_jobs(self) -> list[CronJobModel]:
        async with await self._session_factory() as session:
            stmt = select(CronJobModel).where(CronJobModel.enabled == 1)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    @staticmethod
    def _parse_cron(expression: str) -> dict[str, str]:
        parts = expression.strip().split()
        fields = ["second", "minute", "hour", "day", "month", "day_of_week"]
        if len(parts) == 5:
            fields = ["minute", "hour", "day", "month", "day_of_week"]
        elif len(parts) == 6:
            fields = ["second", "minute", "hour", "day", "month", "day_of_week"]
        else:
            raise ValueError(f"Invalid cron expression: {expression!r} (expected 5 or 6 fields)")
        return dict(zip(fields, parts))

    def _schedule_job(self, model: CronJobModel) -> None:
        if self._aps is None:
            return

        params = json.loads(model.params_json) if model.params_json else {}
        trigger_args = self._parse_cron(model.cron_expression)

        async def run_job() -> None:
            if self._task_queue:
                await self._task_queue.enqueue(model.task_name, params)

            async with await self._session_factory() as session:
                m = await session.get(CronJobModel, model.id)
                if m:
                    m.last_run_at = datetime.now(timezone.utc)
                    await session.commit()

        self._aps.add_job(
            run_job,
            trigger="cron",
            id=model.id,
            replace_existing=True,
            **trigger_args,
        )
