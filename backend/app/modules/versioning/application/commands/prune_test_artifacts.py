from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import UTC, datetime, timedelta
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

        from app.modules.server.infrastructure.models import ServerModel
        from app.modules.versioning.domain.cleanup import TestCleanupPlan
        from app.modules.versioning.domain.paths import resolve_test_dir

        server_ids = {run.server_id for run in expired_runs}
        servers_by_id: dict[str, ServerModel] = {}
        if server_ids:
            srv_res = await session.execute(
                select(ServerModel).where(ServerModel.id.in_(server_ids))
            )
            servers_by_id = {s.id: s for s in srv_res.scalars().all()}

        for run in expired_runs:
            run_server_id = run.server_id
            test_id = run.id
            server = servers_by_id.get(run_server_id)
            if not server or not server.root_path:
                logger.warning(
                    "Skipping artifact cleanup for test %s: "
                    "server %s missing or root_path is NULL; refusing to guess path",
                    test_id,
                    run_server_id,
                )
                run.artifacts_purged = True
                pruned_count += 1
                continue

            root_path = server.root_path
            working_dir = server.working_directory or "."
            server_dir = (
                os.path.join(root_path, working_dir)
                if working_dir != "."
                else root_path
            )

            try:
                test_dir = resolve_test_dir(server_dir, test_id)
                plan = TestCleanupPlan.create(
                    server_id=run_server_id,
                    test_id=test_id,
                    container_name=f"onx-test-{test_id}",
                    test_dir=test_dir,
                    server_dir=server_dir,
                    passed=False,
                    retention_hours=0.0,
                )
                if plan.purge_artifacts and test_dir.exists():
                    await asyncio.to_thread(shutil.rmtree, test_dir, ignore_errors=True)
                    cleaned_dirs.append(str(test_dir))
            except Exception as e:
                logger.warning(
                    "Failed to remove expired test artifact directory for %s: %s",
                    test_id,
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
