from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistence.base import Base
from app.tasks.base import TaskQueue

logger = logging.getLogger("onx.tasks.scheduler")


ALLOWED_SERVER_TASKS: frozenset[str] = frozenset({"run_backup_task"})
ALLOWED_GLOBAL_TASKS: frozenset[str] = frozenset(
    {"run_backup_task", "run_cleanup_task", "run_metrics_collection"}
)
MIN_USER_SCHEDULE_INTERVAL_SECONDS: float = 60.0

_CLEANUP_RETENTION_KEYS: tuple[str, ...] = (
    "retention_days",
    "log_retention_days",
    "event_retention_days",
    "metrics_retention_days",
    "task_retention_days",
    "idempotency_ttl_hours",
)


def validate_cleanup_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Validate cleanup task parameters, enforcing retention >= 1."""
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise ValueError("Cleanup parameters must be a JSON object")
    for key in _CLEANUP_RETENTION_KEYS:
        if key not in params or params[key] is None:
            continue
        val = params[key]
        if isinstance(val, bool) or not isinstance(val, int) or val < 1:
            raise ValueError(f"{key} must be an integer >= 1")
    return params


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
        self._stopping = False

    def set_task_queue(self, queue: TaskQueue) -> None:
        self._task_queue = queue

    def _is_shutdown_cancellation(self) -> bool:
        return self._stopping or not self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stopping = False

        import logging

        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        logging.getLogger("apscheduler.executors.default").setLevel(logging.ERROR)
        self._aps = AsyncIOScheduler()

        jobs = await self._load_jobs()
        for job in jobs:
            try:
                self._schedule_job(job)
            except Exception as exc:
                logger.warning(
                    "Skipping invalid persisted schedule '%s' (%s): %s",
                    getattr(job, "name", "?"),
                    getattr(job, "cron_expression", "?"),
                    exc,
                )

        self._aps.start()

    async def stop(self) -> None:
        self._stopping = True
        self._running = False
        if self._aps:
            self._aps.shutdown(wait=False)

    @classmethod
    def _validate_expression(
        cls,
        expression: str,
        *,
        min_interval_seconds: float = MIN_USER_SCHEDULE_INTERVAL_SECONDS,
    ) -> None:
        import math

        from apscheduler.triggers.cron import CronTrigger

        if not isinstance(expression, str) or not expression.strip():
            raise ValueError(f"Invalid schedule expression: {expression!r}")

        if expression.startswith("interval:"):
            parts = expression.split(":")
            if len(parts) != 2 or not parts[1]:
                raise ValueError(f"Invalid interval expression: {expression!r}")
            secs_str = parts[1].rstrip("s")
            try:
                secs = float(secs_str)
            except ValueError as exc:
                raise ValueError(f"Invalid interval expression: {expression!r}") from exc
            if not math.isfinite(secs) or secs <= 0:
                raise ValueError(
                    f"Interval duration must be a positive finite number: {expression!r}"
                )
            if secs < min_interval_seconds:
                min_s = int(min_interval_seconds)
                raise ValueError(
                    f"Interval duration must be at least {min_s}s: {expression!r}"
                )
        else:
            parsed = cls._parse_cron(expression)
            if min_interval_seconds >= 60.0 and "second" in parsed:
                sec_field = parsed["second"].strip()
                if not sec_field.isdigit() or not (0 <= int(sec_field) <= 59):
                    raise ValueError(
                        f"Sub-minute cron second schedules are not allowed: {expression!r}"
                    )
            try:
                CronTrigger(**parsed)
            except Exception as exc:
                raise ValueError(f"Invalid cron expression {expression!r}: {exc}") from exc

    def _validate_cron_expression(
        self,
        expression: str,
        *,
        min_interval_seconds: float = MIN_USER_SCHEDULE_INTERVAL_SECONDS,
    ) -> None:
        self._validate_expression(expression, min_interval_seconds=min_interval_seconds)

    async def add_job(
        self,
        name: str,
        cron_expression: str,
        task_name: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        min_interval = (
            0.0 if task_name == "run_metrics_collection" else MIN_USER_SCHEDULE_INTERVAL_SECONDS
        )
        self._validate_cron_expression(cron_expression, min_interval_seconds=min_interval)
        job_id = uuid.uuid4().hex
        now = datetime.now(UTC)

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

    async def update_job_expression(self, job_name: str, new_expression: str) -> bool:
        min_interval = (
            0.0
            if job_name == "metrics_collect"
            else MIN_USER_SCHEDULE_INTERVAL_SECONDS
        )
        self._validate_cron_expression(new_expression, min_interval_seconds=min_interval)
        async with await self._session_factory() as session:
            stmt = select(CronJobModel).where(CronJobModel.name == job_name)
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()
            if model is None:
                return False
            model.cron_expression = new_expression
            await session.commit()

        if self._aps:
            self._schedule_job(model)
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
        resolved_task_name = (
            "run_backup_task" if model.task_name == "backup" else model.task_name
        )
        dispatch_params = (
            {**params, "scheduled": True}
            if resolved_task_name == "run_backup_task" and "backup_id" not in params
            else params
        )

        is_subminute_interval = False
        if model.cron_expression.startswith("interval:"):
            secs_str = model.cron_expression.split(":")[1].rstrip("s")
            secs = float(secs_str)
            if secs < 10.0:
                is_subminute_interval = True
            trigger_type = "interval"
            trigger_kwargs = {"seconds": secs}
        else:
            trigger_type = "cron"
            trigger_kwargs = self._parse_cron(model.cron_expression)

        async def run_job() -> None:
            try:
                if (
                    is_subminute_interval
                    and self._task_queue
                    and hasattr(self._task_queue, "_handlers")
                ):
                    handler = self._task_queue._handlers.get(resolved_task_name)
                    if handler:
                        try:
                            await handler(dispatch_params)
                        except asyncio.CancelledError:
                            if self._is_shutdown_cancellation():
                                logger.debug(
                                    'Sub-minute task "%s" cancelled during scheduler shutdown',
                                    resolved_task_name,
                                )
                                return
                            raise
                        except Exception:
                            logger.exception(
                                'Sub-minute task "%s" failed (direct execution)',
                                resolved_task_name,
                            )
                    else:
                        await self._task_queue.enqueue(resolved_task_name, dispatch_params)
                elif self._task_queue:
                    await self._task_queue.enqueue(resolved_task_name, dispatch_params)

                if not is_subminute_interval:
                    try:
                        async with await self._session_factory() as session:
                            m = await session.get(CronJobModel, model.id)
                            if m:
                                m.last_run_at = datetime.now(UTC)
                                await session.commit()
                    except asyncio.CancelledError:
                        if self._is_shutdown_cancellation():
                            logger.debug(
                                'Job "%s" timestamp update cancelled during scheduler shutdown',
                                model.id,
                            )
                            return
                        raise
                    except Exception as exc:
                        logger.warning(
                            "Failed to update last_run_at for job %s: %s",
                            model.id,
                            exc,
                            exc_info=True,
                        )
            except asyncio.CancelledError:
                if self._is_shutdown_cancellation():
                    logger.debug(
                        'Scheduled job "%s" (%s) cancelled during scheduler shutdown',
                        model.name,
                        model.task_name,
                    )
                    return
                raise

        # misfire_grace_time=60: absorbs I/O bursts (DB queries, RCON polls, backup writes)
        # without silently dropping scheduled jobs.
        self._aps.add_job(
            run_job,
            trigger=trigger_type,
            id=model.id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
            **trigger_kwargs,
        )


_global_scheduler: Scheduler | None = None


def init_global_scheduler(scheduler: Scheduler) -> None:
    global _global_scheduler
    _global_scheduler = scheduler


def get_scheduler() -> Scheduler | None:
    return _global_scheduler
