from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.config import AppSettings
from app.core.identity import IDENTITY
from app.modules.versioning.domain.value_objects import TestRunStatus
from app.modules.versioning.infrastructure.models import ServerTestRunModel

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.versioning.prune_artifacts")


class PruneTestArtifactsCommand(Command):
    server_id: str | None = None
    retention_hours: float | None = None
    now: datetime | None = None


class PruneTestArtifactsHandler(CommandHandler[PruneTestArtifactsCommand]):
    async def handle(self, command: PruneTestArtifactsCommand) -> CommandResult:
        from app.core.persistence.db import database

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with database.session_factory() as session:
                    res = await self.execute_pruning(
                        session=session,
                        server_id=command.server_id,
                        retention_hours=command.retention_hours,
                        now=command.now,
                    )
                    await session.commit()
                return res
            except Exception as exc:
                is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if is_lock and attempt < max_retries - 1:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                raise

    @classmethod
    async def execute_pruning(
        cls,
        session: Any,
        server_id: str | None = None,
        retention_hours: float | None = None,
        now: datetime | None = None,
    ) -> CommandResult:
        settings = AppSettings()
        hours = (
            retention_hours
            if retention_hours is not None
            else getattr(settings, "test_artifact_retention_hours", 24)
        )
        at = now or datetime.now(UTC)
        cutoff = at - timedelta(hours=hours)

        failed_statuses = [TestRunStatus.FAILED.value, TestRunStatus.CANCELLED.value]
        stmt = select(ServerTestRunModel).where(
            ServerTestRunModel.status.in_(failed_statuses),
            ServerTestRunModel.artifacts_purged.is_(False),
            ServerTestRunModel.created_at < cutoff,
        )
        if server_id is not None:
            stmt = stmt.where(ServerTestRunModel.server_id == server_id)

        res = await session.execute(stmt)
        expired_runs = res.scalars().all()

        pruned_count = 0
        cleaned_dirs: list[str] = []

        servers_root = Path(settings.servers_data_dir).resolve()

        for run in expired_runs:
            run_server_id = run.server_id
            test_id = run.id
            test_dir = servers_root / run_server_id / ".onx" / "tests" / test_id

            if test_dir.exists():
                try:
                    await asyncio.to_thread(shutil.rmtree, test_dir, ignore_errors=True)
                    cleaned_dirs.append(str(test_dir))
                except Exception as e:
                    logger.warning(
                        "Failed to remove expired test artifact directory %s: %s",
                        test_dir,
                        e,
                    )

            run.artifacts_purged = True
            pruned_count += 1

        return CommandResult(
            success=True,
            entity_id=server_id or "global",
            details={
                "pruned_count": pruned_count,
                "cleaned_directories": cleaned_dirs,
                "cutoff": cutoff.isoformat(),
            },
        )
