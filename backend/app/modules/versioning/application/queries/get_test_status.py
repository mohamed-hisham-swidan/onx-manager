from __future__ import annotations

from typing import Any

from app.core.exceptions import NotFoundError
from app.core.query_bus import Query, QueryHandler
from app.modules.versioning.domain.repository import VersioningRepository


class GetTestStatusQuery(Query):
    server_id: str
    test_id: str


class GetTestStatusHandler(QueryHandler[GetTestStatusQuery]):
    def __init__(self, versioning_repo: VersioningRepository | None = None) -> None:
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetTestStatusQuery) -> dict[str, Any]:
        from app.core.persistence.db import database
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._versioning_repo is not None:
            repo = self._versioning_repo
            test_run = await repo.get_test_run(query.test_id)
        else:
            async with database.session_factory() as session:
                repo = SQLVersioningRepository(session)
                test_run = await repo.get_test_run(query.test_id)

        if test_run is None or test_run.server_id != query.server_id:
            raise NotFoundError(
                f"Test run '{query.test_id}' not found for server '{query.server_id}'"
            )

        return {
            "id": test_run.id,
            "server_id": test_run.server_id,
            "commit_id": test_run.commit_id,
            "node_id": test_run.node_id,
            "status": test_run.status.value
            if hasattr(test_run.status, "value")
            else str(test_run.status),
            "ephemeral_port": test_run.ephemeral_port,
            "log_output": test_run.log_output,
            "failure_reason": test_run.failure_reason,
            "created_at": (
                test_run.created_at.isoformat()
                if hasattr(test_run.created_at, "isoformat")
                else str(test_run.created_at)
            ),
            "expires_at": (
                test_run.expires_at.isoformat()
                if test_run.expires_at and hasattr(test_run.expires_at, "isoformat")
                else None
            ),
            "bot_count": test_run.bot_count,
            "duration_minutes": test_run.duration_minutes,
            "placement_mode": (
                test_run.placement_mode.value
                if hasattr(test_run.placement_mode, "value")
                else str(test_run.placement_mode)
            ),
            "bot_tech": (
                test_run.bot_tech.value
                if hasattr(test_run.bot_tech, "value")
                else str(test_run.bot_tech)
            ),
        }
