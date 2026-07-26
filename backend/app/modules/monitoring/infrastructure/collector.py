from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.event_bus import DomainEvent, EventBus
from app.modules.monitoring.domain.aggregate import MetricPoint
from app.modules.monitoring.infrastructure.repository import SQLMetricRepository
from app.modules.shared.value_objects import ServerId
from app.storage.db import database

logger = logging.getLogger(__name__)


@dataclass
class ServerMetrics:
    server_id: str
    tps: float = 20.0
    players: int = 0
    ram_used_mb: float = 0.0
    cpu_percent: float = 0.0
    uptime_seconds: float = 0.0
    world_size_bytes: int = 0


class MetricsCollector:
    def __init__(self, event_bus: EventBus | None = None, known_servers: list[str] | None = None) -> None:
        self._event_bus = event_bus
        self._known_servers = known_servers or []

    def set_known_servers(self, server_ids: list[str]) -> None:
        self._known_servers = list(server_ids)

    async def collect(self, server_id: str) -> ServerMetrics:
        metric = ServerMetrics(server_id=server_id)
        try:
            point = MetricPoint(
                tps=metric.tps,
                players=metric.players,
                ram_used_mb=metric.ram_used_mb,
                cpu_percent=metric.cpu_percent,
                timestamp=datetime.now(timezone.utc),
            )

            async with database.session_factory() as session:
                repo = SQLMetricRepository(session)
                sid = ServerId(server_id)
                await repo.record(sid, point)

            if self._event_bus:
                await self._event_bus.publish(
                    MetricCollectedEvent(
                        server_id=server_id,
                        tps=metric.tps,
                        players=metric.players,
                        ram_mb=metric.ram_used_mb,
                        cpu=metric.cpu_percent,
                    ),
                )

        except Exception as e:
            logger.warning("Metrics collection failed for %s: %s", server_id, e)

        return metric

    async def collect_all(self) -> dict[str, ServerMetrics]:
        results: dict[str, ServerMetrics] = {}
        for server_id in self._known_servers:
            results[server_id] = await self.collect(server_id)
        return results


class MetricCollectedEvent(DomainEvent):
    server_id: str
    tps: float = 0.0
    players: int = 0
    ram_mb: float = 0.0
    cpu: float = 0.0
