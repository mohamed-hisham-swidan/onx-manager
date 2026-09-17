from __future__ import annotations

from typing import Any

from app.core.exceptions import NotFoundError
from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.dag import traverse_history
from app.modules.versioning.domain.repository import VersioningRepository


class GetBranchHistoryQuery(Query):
    server_id: str
    branch_name: str
    limit: int = 100


class GetBranchHistoryHandler(QueryHandler[GetBranchHistoryQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetBranchHistoryQuery) -> list[dict[str, Any]]:
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
        query: GetBranchHistoryQuery,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> list[dict[str, Any]]:
        from app.modules.shared.value_objects import ServerId

        try:
            await server_repo.get(ServerId(query.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{query.server_id}' not found") from exc

        branch = await versioning_repo.get_branch_by_name(query.server_id, query.branch_name)
        if branch is None:
            raise NotFoundError(
                f"Branch '{query.branch_name}' not found on server '{query.server_id}'"
            )

        if branch.head_commit_id is None:
            return []

        commits = await traverse_history(
            start_commit_id=branch.head_commit_id,
            get_commit_func=versioning_repo.get_commit,
            get_parents_func=versioning_repo.get_commit_parents,
            limit=query.limit,
        )

        return [
            {
                "id": c.id,
                "server_id": c.server_id,
                "message": c.message,
                "branch_id": c.branch_id,
                "parent_commit_id": c.parent_commit_id,
                "parent_commit_ids": c.parent_commit_ids,
                "author_id": c.author_id,
                "world_snapshot_id": c.world_snapshot_id,
                "created_at": c.created_at.isoformat(),
                "manifest": c.manifest.to_dict(),
            }
            for c in commits
        ]
