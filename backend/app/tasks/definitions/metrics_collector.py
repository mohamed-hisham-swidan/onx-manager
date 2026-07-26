from __future__ import annotations

import logging
from typing import Any

from app.modules.monitoring.infrastructure.collector import MetricsCollector
from app.modules.monitoring.infrastructure.metrics import PrometheusMetricsRegistry

logger = logging.getLogger(__name__)


async def run_metrics_collection_task(params: dict[str, Any]) -> dict[str, Any]:
    collector: MetricsCollector = params["collector"]
    prometheus: PrometheusMetricsRegistry = params.get("prometheus")

    results = await collector.collect_all()

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
