from __future__ import annotations

from typing import Any

from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import MaterializationStatus


class GetMaterializationsQuery(Query):
    server_id: str


class GetMaterializationsHandler(QueryHandler[GetMaterializationsQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetMaterializationsQuery) -> list[dict[str, Any]]:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None and self._versioning_repo is not None:
            return await self._execute(query, self._server_repo, self._versioning_repo)

        async with database.session_factory() as session:
            server_repo = SQLServerRepository(session)
            versioning_repo = SQLVersioningRepository(session)
            res = await self._execute(query, server_repo, versioning_repo)
            await session.commit()
            return res

    async def _execute(
        self,
        query: GetMaterializationsQuery,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> list[dict[str, Any]]:
        _ = server_repo
        mats = await versioning_repo.list_materializations(query.server_id)
        results: list[dict[str, Any]] = []

        for mat in mats:
            stale = mat.status == MaterializationStatus.STALE

            # Lazy staleness check for branch-derived materializations
            if (
                not stale
                and mat.status == MaterializationStatus.READY
                and mat.revision.startswith("branch:")
            ):
                parts = mat.revision.split("@", 1)
                branch_name = parts[0].replace("branch:", "")
                branch = await versioning_repo.get_branch_by_name(query.server_id, branch_name)
                if branch and branch.head_commit_id and branch.head_commit_id != mat.commit_id:
                    mat.mark_stale()
                    await versioning_repo.save_materialization(mat)
                    stale = True


            results.append(
                {
                    "id": mat.id,
                    "revision": mat.revision,
                    "mode": mat.mode.value,
                    "status": mat.status.value,
                    "stale": stale,
                    "created_at": mat.created_at.isoformat(),
                }
            )

        return results
