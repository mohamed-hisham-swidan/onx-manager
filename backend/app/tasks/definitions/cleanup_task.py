from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, text

from app.core.persistence.db import database
from app.tasks.scheduler import validate_cleanup_params

logger = logging.getLogger(__name__)


async def run_cleanup_task(params: dict[str, Any]) -> dict[str, Any]:
    validated = validate_cleanup_params(params)
    async with database.session_factory() as session:
        counts: dict[str, int] = {}

        if validated.get("cleanup_logs", True):
            from app.modules.auth.infrastructure.audit import AuditLogModel

            cutoff = datetime.now(UTC) - timedelta(days=validated.get("log_retention_days", 30))
            result = await session.execute(
                delete(AuditLogModel).where(AuditLogModel.timestamp < cutoff),
            )
            counts["logs_deleted"] = result.rowcount if result.rowcount != -1 else 0

        if validated.get("cleanup_idempotency", True):
            ttl_hours = validated.get("idempotency_ttl_hours")
            if ttl_hours is None:
                try:
                    from app.core.settings_store import get_live_settings

                    ttl_hours = get_live_settings().idempotency_ttl_hours
                except RuntimeError:
                    ttl_hours = 24
            cutoff = datetime.now(UTC) - timedelta(hours=max(1, int(ttl_hours)))
            result = await session.execute(
                text("DELETE FROM idempotency_keys WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
            counts["idempotency_keys_deleted"] = result.rowcount if result.rowcount != -1 else 0

        if validated.get("cleanup_events", True):
            cutoff = datetime.now(UTC) - timedelta(days=validated.get("event_retention_days", 90))
            result = await session.execute(
                text("DELETE FROM event_store WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
            counts["events_deleted"] = result.rowcount if result.rowcount != -1 else 0

        if validated.get("cleanup_metrics", True):
            cutoff = datetime.now(UTC) - timedelta(
                days=validated.get("metrics_retention_days", 7)
            )
            result = await session.execute(
                text("DELETE FROM metric_points WHERE recorded_at < :cutoff"),
                {"cutoff": cutoff},
            )
            counts["metric_points_deleted"] = result.rowcount if result.rowcount != -1 else 0

        if validated.get("cleanup_refresh_tokens", True):
            now_utc = datetime.now(UTC)
            result = await session.execute(
                text(
                    "DELETE FROM refresh_tokens WHERE expires_at < :now OR is_revoked = 1"
                ),
                {"now": now_utc},
            )
            counts["refresh_tokens_deleted"] = result.rowcount if result.rowcount != -1 else 0

        if validated.get("cleanup_task_queue", True):
            cutoff = datetime.now(UTC) - timedelta(days=validated.get("task_retention_days", 7))
            result = await session.execute(
                text("DELETE FROM task_queue WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
            counts["tasks_deleted"] = result.rowcount if result.rowcount != -1 else 0

        await session.commit()

    logger.info("Cleanup task completed: %s", counts)
    return counts
