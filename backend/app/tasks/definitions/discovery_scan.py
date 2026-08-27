from __future__ import annotations

import logging
from typing import Any

from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.server.application.discovery.engine import run_discovery_scan
from app.modules.server.infrastructure.repository import SQLServerRepository

logger = logging.getLogger(__name__)


async def periodic_discovery_scan(params: dict[str, Any]) -> dict[str, Any]:
    event_bus: EventBus = params["event_bus"]
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        result = await run_discovery_scan(repo, event_bus)
    logger.info(
        "Periodic discovery scan: %d new, %d already known",
        result["discovered"],
        result["already_known"],
    )
    return result
