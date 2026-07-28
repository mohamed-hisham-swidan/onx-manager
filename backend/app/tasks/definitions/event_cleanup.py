from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.event_store.models import StoredEventModel
from app.core.persistence.db import database

logger = logging.getLogger(__name__)


async def run_event_cleanup_task(params: dict[str, Any]) -> dict[str, Any]:
    async with await database.session_factory() as session:
        retention_policies: list[tuple[str, int]] = [
            ("raw", params.get("raw_retention_hours", 2)),
            ("1m_rollup", params.get("rollup_1m_retention_days", 30)),
            ("1h_rollup", params.get("rollup_1h_retention_days", 365)),
            ("1d_summary", params.get("summary_retention_days", 3650)),
        ]

        results: dict[str, int] = {}

        for resolution, ttl_hours in retention_policies:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
            stmt = (
                select(StoredEventModel)
                .where(
                    StoredEventModel.created_at < cutoff,
                    text("event_type LIKE :pattern"),
                )
                .limit(1000)
            )
            if resolution == "raw":
                stmt = stmt.params(pattern="metric.%")
            else:
                stmt = stmt.params(pattern=f"metric.{resolution}.%")

            result = await session.execute(stmt)
            events = list(result.scalars().all())
            for event in events:
                await session.delete(event)
            results[resolution] = len(events)

        await session.commit()

    logger.info("Event cleanup completed: %s", results)
    return results
