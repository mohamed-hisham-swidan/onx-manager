from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.health.infrastructure.integrity import FilesystemIntegrityChecker
from app.modules.health.infrastructure.repository import SQLIntegrityRepository
from app.modules.server.infrastructure.repository import SQLServerRepository

logger = logging.getLogger("mcs.tasks.integrity")


async def scan_all_servers(params: dict[str, Any] | None = None) -> dict[str, Any]:
    scope = (params or {}).get("scope", "quick")
    async with database.session_factory() as session:
        server_repo = SQLServerRepository(session)
        all_servers = await server_repo.list()
    results: dict[str, str] = {}
    for server in all_servers:
        try:
            async with database.session_factory() as session:
                integrity_repo = SQLIntegrityRepository(session)
                checker = FilesystemIntegrityChecker(integrity_repo=integrity_repo)
                report = await checker.check(server.server_id, scope=scope)
                await integrity_repo.save_audit(report)
            results[server.server_id] = report.overall_status
            logger.info(
                "Integrity scan server=%s status=%s scope=%s",
                server.server_id, report.overall_status, scope,
            )
        except Exception:
            logger.exception("Integrity scan failed for server=%s", server.server_id)
            results[server.server_id] = "error"
    return {
        "scanned": len(results),
        "results": results,
    }


async def cleanup_old_audits(params: dict[str, Any] | None = None) -> dict[str, Any]:
    from sqlalchemy import delete

    from app.modules.health.infrastructure.models import IntegrityAuditModel

    retention_days = (params or {}).get("retention_days", 90)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    async with database.session_factory() as session:
        stmt = (
            delete(IntegrityAuditModel)
            .where(IntegrityAuditModel.checked_at < cutoff)
        )
        result = await session.execute(stmt)
        await session.commit()
        deleted = result.rowcount
    logger.info("Cleaned up %d audit records older than %d days", deleted, retention_days)
    return {"deleted": deleted, "retention_days": retention_days}
