import asyncio
import logging
import time
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
_last_healthy_log_time: float = 0.0
_HEARTBEAT_LOG_INTERVAL_SECONDS: float = 120.0  # Log healthy summary once every 2 minutes


def init_collector(
    collector: MetricsCollector,
    prometheus: PrometheusMetricsRegistry | None = None,
) -> None:
    global _collector, _prometheus
    _collector = collector
    _prometheus = prometheus


async def run_metrics_collection_task(params: dict[str, Any]) -> dict[str, Any]:
    if _collection_lock.locked():
        logger.debug("Metrics collection already in progress — skipping overlapping cycle")
        return {"server_count": 0, "results": {}, "skipped": True}

    async with _collection_lock:
        return await _run_collection(params)


async def _run_collection(_params: dict[str, Any]) -> dict[str, Any]:
    global _last_healthy_log_time
    collector = _collector
    if collector is None:
        logger.warning("MetricsCollector not initialized — skipping collection")
        return {"server_count": 0, "results": {}}

    test_ids: list[str] = []
    try:
        async with database.session_factory() as session:
            stmt = select(ServerModel.id).where(ServerModel.status == "running")
            result = await session.execute(stmt)
            server_ids = [row[0] for row in result]
            collector.set_known_servers(server_ids)

            from app.modules.versioning.infrastructure.models import ServerTestRunModel

            stmt_test = select(ServerTestRunModel.id).where(
                ServerTestRunModel.status.in_(["BOOTING", "RUNNING"])
            )
            res_test = await session.execute(stmt_test)
            test_ids = [row[0] for row in res_test]
    except Exception:
        logger.exception("Failed to refresh known servers from DB")

    try:
        if test_ids:
            results = await collector.collect_all(test_ids=test_ids)
        else:
            results = await collector.collect_all()
    except TypeError:
        results = await collector.collect_all()

    prometheus = _prometheus
    if prometheus is not None:
        for server_id, metrics in results.items():
            if metrics.tps is not None:
                prometheus.update_tps(server_id, metrics.tps)
            prometheus.update_players(server_id, metrics.players)
            prometheus.update_ram(server_id, metrics.ram_used_mb)
            prometheus.update_cpu(server_id, metrics.cpu_percent)

    now = time.time()
    if now - _last_healthy_log_time >= _HEARTBEAT_LOG_INTERVAL_SECONDS:
        _last_healthy_log_time = now
        logger.debug("Metrics collection running normally (%d active server(s))", len(results))

    return {
        "server_count": len(results),
        "results": {
            sid: {"tps": m.tps, "players": m.players, "ram_mb": m.ram_used_mb, "cpu": m.cpu_percent}
            for sid, m in results.items()
        },
    }
