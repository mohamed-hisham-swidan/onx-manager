from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.modules.monitoring.infrastructure.metrics import PrometheusMetricsRegistry
from app.storage.db import database

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class HealthResult:
    status: str  # "up" | "degraded" | "down"
    detail: str = ""
    latency_ms: float = 0.0


class HealthCheckRegistry:
    def __init__(self, prometheus: PrometheusMetricsRegistry | None = None) -> None:
        self._checks: dict[str, Callable[[], Awaitable[HealthResult]]] = {}
        self._prometheus = prometheus

    def register(
        self,
        name: str,
        check: Callable[[], Awaitable[HealthResult]],
    ) -> None:
        self._checks[name] = check

    async def run_all(self) -> dict[str, HealthResult]:
        results: dict[str, HealthResult] = {}
        tasks = []
        for name, check in self._checks.items():
            tasks.append(self._run_one(name, check))

        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        for name, outcome in zip(self._checks.keys(), outcomes):
            if isinstance(outcome, Exception):
                results[name] = HealthResult(status="down", detail=str(outcome))
            else:
                results[name] = outcome

        if self._prometheus is not None:
            for name, result in results.items():
                self._prometheus.update_health(name, result.status)

        return results

    async def _run_one(
        self,
        name: str,
        check: Callable[[], Awaitable[HealthResult]],
    ) -> HealthResult:
        start = time.monotonic()
        result = await check()
        elapsed = (time.monotonic() - start) * 1000
        result.latency_ms = round(elapsed, 2)
        return result


async def check_database() -> HealthResult:
    try:
        async with database.session_factory() as session:
            await session.execute("SELECT 1")
        return HealthResult(status="up", detail="Database reachable")
    except Exception as e:
        return HealthResult(status="down", detail=str(e))


async def check_disk() -> HealthResult:
    import shutil
    try:
        usage = shutil.disk_usage("/")
        free_gb = usage.free / (1024**3)
        if free_gb < 0.5:
            return HealthResult(status="degraded", detail=f"Disk space critically low: {free_gb:.1f} GB free")
        return HealthResult(status="up", detail=f"{free_gb:.1f} GB free")
    except Exception as e:
        return HealthResult(status="degraded", detail=str(e))


async def check_dlq_depth(event_store: Any) -> HealthResult:
    from app.modules.event_store.repository import SQLEventRepository

    async with database.session_factory() as session:
        repo = SQLEventRepository(session)
        count = len(await repo.list_dead_letters(limit=1))
        if count > 0:
            return HealthResult(status="degraded", detail=f"{count} messages in dead letter queue")
        return HealthResult(status="up", detail="No dead letters")
