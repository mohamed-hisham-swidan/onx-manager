from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from dataclasses import dataclass

from app.modules.versioning.domain.cleanup import TestCleanupPlan

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CleanupResult:
    container_removed: bool
    artifacts_purged: bool
    error: str | None = None


async def execute_cleanup_plan(plan: TestCleanupPlan) -> CleanupResult:
    """Executes the physical teardown actions defined by a pure domain TestCleanupPlan."""
    container_removed = False
    artifacts_purged = False
    error_msg = None

    # 1. Remove docker container if requested
    if plan.remove_container:
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["docker", "rm", "-f", plan.container_name],
                capture_output=True,
                text=True,
                timeout=15,
            )
            container_removed = True
        except Exception as exc:
            logger.debug("Failed to remove test container %s: %s", plan.container_name, exc)
            error_msg = str(exc)

    # 2. Purge test directory if requested
    if plan.purge_artifacts:
        try:
            if plan.test_dir.exists():
                await asyncio.to_thread(shutil.rmtree, plan.test_dir, ignore_errors=True)
                if not plan.test_dir.exists():
                    artifacts_purged = True
        except Exception as exc:
            logger.warning("Failed to remove test directory %s: %s", plan.test_dir, exc)
            error_msg = str(exc)

    return CleanupResult(
        container_removed=container_removed,
        artifacts_purged=artifacts_purged,
        error=error_msg,
    )
