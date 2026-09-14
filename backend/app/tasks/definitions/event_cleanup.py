from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text

from app.core.persistence.db import database
from app.modules.activity.infrastructure.repository import SQLActivityRepository
from app.modules.event_store.models import StoredEventModel

logger = logging.getLogger(__name__)


async def run_event_cleanup_task(params: dict[str, Any]) -> dict[str, Any]:
    async with database.session_factory() as session:
        retention_policies: list[tuple[str, timedelta]] = [
            ("raw", timedelta(hours=params.get("raw_retention_hours", 2))),
            ("1m_rollup", timedelta(days=params.get("rollup_1m_retention_days", 30))),
            ("1h_rollup", timedelta(days=params.get("rollup_1h_retention_days", 365))),
            ("1d_summary", timedelta(days=params.get("summary_retention_days", 3650))),
        ]

        results: dict[str, int] = {}

        for resolution, delta in retention_policies:
            cutoff = datetime.now(UTC) - delta
            stmt = (
                select(StoredEventModel)
                .where(
                    StoredEventModel.created_at < cutoff,
                    text("event_type LIKE :pattern"),
                )
                .limit(1000)
            )
            if resolution == "raw":
                stmt = stmt.where(
                    text("event_type NOT LIKE 'metric.1m_rollup.%'"),
                    text("event_type NOT LIKE 'metric.1h_rollup.%'"),
                    text("event_type NOT LIKE 'metric.1d_summary.%'"),
                ).params(pattern="metric.%")
            else:
                stmt = stmt.params(pattern=f"metric.{resolution}.%")

            result = await session.execute(stmt)
            events = list(result.scalars().all())
            for event in events:
                await session.delete(event)
            results[resolution] = len(events)

        # Activity log retention (Feature 4 - Change History Log: 90 days default)
        activity_retention_days = params.get("activity_log_retention_days", 90)
        activity_cutoff = time.time() - (activity_retention_days * 86400)
        activity_repo = SQLActivityRepository(session=session)
        deleted_activity = await activity_repo.delete_older_than(activity_cutoff)
        results["activity_logs"] = deleted_activity

        await session.commit()

    logger.info("Event cleanup completed: %s", results)
    return results
