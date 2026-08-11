from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from app.core.persistence.db import database
from app.modules.monitoring.infrastructure.collector import MetricsCollector
from app.modules.monitoring.infrastructure.metrics import PrometheusMetricsRegistry
from app.modules.server.infrastructure.models import ServerModel

logger = logging.getLogger(__name__)

_collector: MetricsCollector | None = None
_prometheus: PrometheusMetricsRegistry | None = None
_collection_lock = asyncio.Lock()


def init_collector(
    collector: MetricsCollector,
    prometheus: PrometheusMetricsRegistry | None = None,
) -> None:
    global _collector, _prometheus
    _collector = collector
    _prometheus = prometheus


async def run_metrics_collection_task(params: dict[str, Any]) -> dict[str, Any]:
    if _collection_lock.locked():
        logger.warning("Metrics collection already in progress — skipping overlapping cycle")
        return {"server_count": 0, "results": {}, "skipped": True}

    async with _collection_lock:
        return await _run_collection(params)


async def _run_collection(params: dict[str, Any]) -> dict[str, Any]:
    collector = _collector
    if collector is None:
        logger.warning("MetricsCollector not initialized — skipping collection")
        return {"server_count": 0, "results": {}}

    try:
        async with database.session_factory() as session:
            stmt = select(ServerModel.id).where(ServerModel.status == "running")
            result = await session.execute(stmt)
            server_ids = [row[0] for row in result]
            collector.set_known_servers(server_ids)
    except Exception:
        logger.exception("Failed to refresh known servers from DB")

    results = await collector.collect_all()

    prometheus = _prometheus
    if prometheus is not None:
        for server_id, metrics in results.items():
            prometheus.update_tps(server_id, metrics.tps)
            prometheus.update_players(server_id, metrics.players)
            prometheus.update_ram(server_id, metrics.ram_used_mb)
            prometheus.update_cpu(server_id, metrics.cpu_percent)

    logger.info("Metrics collection completed for %d servers", len(results))
    return {
        "server_count": len(results),
        "results": {
            sid: {"tps": m.tps, "players": m.players, "ram_mb": m.ram_used_mb, "cpu": m.cpu_percent}
            for sid, m in results.items()
        },
    }
