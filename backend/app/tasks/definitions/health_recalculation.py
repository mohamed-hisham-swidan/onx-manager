from __future__ import annotations

import logging
from typing import Any

from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.health.application.commands.evaluate_health import (
    EvaluateHealthCommand,
    EvaluateHealthHandler,
)

logger = logging.getLogger("onx.tasks.health_recalculation")


async def periodic_health_recalculation(params: dict[str, Any]) -> dict[str, Any]:
    event_bus: EventBus | None = params.get("event_bus")
    if event_bus is None or not isinstance(event_bus, EventBus):
        try:
            from app.api.deps import get_event_bus

            event_bus = await get_event_bus()
        except (ImportError, RuntimeError):
            event_bus = EventBus()

    handler = EvaluateHealthHandler(event_bus)
    processed = 0

    async with database.session_factory() as session:
        from sqlalchemy import select

        from app.modules.health.infrastructure.models import HealthStatusModel

        stmt = select(HealthStatusModel.server_id)
        result = await session.execute(stmt)
        server_ids = [row[0] for row in result.all()]

    for sid in server_ids:
        try:
            cmd = EvaluateHealthCommand(server_id=sid)
            result = await handler.handle(cmd)
            if result.success:
                processed += 1
        except Exception as exc:
            logger.warning("Health recalculation failed for server %s: %s", sid, exc)

    logger.info("Health recalculation complete: %d/%d servers updated", processed, len(server_ids))
    return {"success": True, "processed": processed, "total": len(server_ids)}
