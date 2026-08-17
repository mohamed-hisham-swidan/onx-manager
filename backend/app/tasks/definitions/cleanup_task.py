from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistence.db import database

logger = logging.getLogger(__name__)


async def run_cleanup_task(params: dict[str, Any]) -> dict[str, Any]:
    async with database.session_factory() as session:
        counts: dict[str, int] = {}

        if params.get("cleanup_logs", True):
            from app.modules.auth.infrastructure.audit import AuditLogModel
            cutoff = datetime.now(timezone.utc) - timedelta(days=params.get("log_retention_days", 30))
            result = await session.execute(
                delete(AuditLogModel).where(AuditLogModel.created_at < cutoff),
            )
            counts["logs_deleted"] = result.rowcount if result.rowcount != -1 else 0

        if params.get("cleanup_idempotency", True):
            ttl_hours = params.get("idempotency_ttl_hours")
            if ttl_hours is None:
                try:
                    from app.core.settings_store import get_live_settings
                    ttl_hours = get_live_settings().idempotency_ttl_hours
                except RuntimeError:
                    ttl_hours = 24
            cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
            result = await session.execute(
                text("DELETE FROM idempotency_keys WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
            counts["idempotency_keys_deleted"] = result.rowcount if result.rowcount != -1 else 0

        if params.get("cleanup_events", True):
            cutoff = datetime.now(timezone.utc) - timedelta(days=params.get("event_retention_days", 90))
            result = await session.execute(
                delete("event_store").where(text("created_at < :cutoff")),
                {"cutoff": cutoff},
            )
            counts["events_deleted"] = result.rowcount if result.rowcount != -1 else 0

        if params.get("cleanup_task_queue", True):
            cutoff = datetime.now(timezone.utc) - timedelta(days=params.get("task_retention_days", 7))
            result = await session.execute(
                delete("task_queue").where(text("created_at < :cutoff")),
                {"cutoff": cutoff},
            )
            counts["tasks_deleted"] = result.rowcount if result.rowcount != -1 else 0

        await session.commit()

    logger.info("Cleanup task completed: %s", counts)
    return counts
