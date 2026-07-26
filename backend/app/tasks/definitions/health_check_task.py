from __future__ import annotations

import logging
from typing import Any

from app.modules.monitoring.infrastructure.health import HealthCheckRegistry

logger = logging.getLogger(__name__)


async def run_health_check_task(params: dict[str, Any]) -> dict[str, Any]:
    registry: HealthCheckRegistry = params["registry"]
    results = await registry.run_all()
    logger.info("Health check task completed: %d checks", len(results))
    return {"check_count": len(results), "results": {k: v.status for k, v in results.items()}}
