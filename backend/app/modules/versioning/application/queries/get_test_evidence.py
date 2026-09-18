from __future__ import annotations

from typing import Any

from app.core.exceptions import NotFoundError
from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.repository import ServerRepository
from app.modules.shared.value_objects import ServerId
from app.modules.versioning.domain.repository import VersioningRepository


class GetTestRunEvidenceQuery(Query):
    server_id: str
    test_id: str


class GetTestRunEvidenceHandler(QueryHandler[GetTestRunEvidenceQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetTestRunEvidenceQuery) -> dict[str, Any]:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None and self._versioning_repo is not None:
            return await self._execute(query, self._server_repo, self._versioning_repo)

        async with database.session_factory() as session:
            server_repo = SQLServerRepository(session)
            versioning_repo = SQLVersioningRepository(session)
            return await self._execute(query, server_repo, versioning_repo)

    async def _execute(
        self,
        query: GetTestRunEvidenceQuery,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> dict[str, Any]:
        try:
            await server_repo.get(ServerId(query.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{query.server_id}' not found") from exc

        run = await versioning_repo.get_test_run(query.test_id)
        if run is None or run.server_id != query.server_id:
            raise NotFoundError(
                f"Test run '{query.test_id}' not found for server '{query.server_id}'"
            )

        if run.evidence_bundle:
            return run.evidence_bundle

        # Synthesize fallback evidence bundle if not explicitly recorded
        runtime_dict: dict[str, Any] = {}
        if run.runtime_id:
            rt = await versioning_repo.get_runtime(run.runtime_id)
            if rt:
                runtime_dict = {
                    "runtime_id": rt.id,
                    "container_id": rt.container_id,
                    "status": rt.status.value if hasattr(rt.status, "value") else str(rt.status),
                    "exit_code": rt.exit_code,
                    "oom_killed": rt.oom_killed,
                }

        log_lines = run.log_output.splitlines()[-100:] if run.log_output else []

        return {
            "test_id": run.id,
            "server_id": run.server_id,
            "commit_id": run.commit_id,
            "runtime": runtime_dict,
            "assertions": {
                "container_started": bool(run.ephemeral_port or runtime_dict.get("container_id")),
                "bots_spawned_target": run.bot_count,
                "clean_shutdown": run.is_terminal and run.status.value == "PASSED",
            },
            "crash_analysis": {
                "failure_reason": run.failure_reason,
            },
            "log_tail": log_lines,
        }
