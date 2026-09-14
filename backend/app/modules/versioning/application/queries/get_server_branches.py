from __future__ import annotations

from typing import Any

from app.core.query_bus import Query, QueryHandler
from app.modules.versioning.domain.repository import VersioningRepository


class GetServerBranchesQuery(Query):
    server_id: str


class GetServerBranchesHandler(QueryHandler[GetServerBranchesQuery]):
    def __init__(self, versioning_repo: VersioningRepository | None = None) -> None:
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetServerBranchesQuery) -> list[dict[str, Any]]:
        from app.core.persistence.db import database
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._versioning_repo is not None:
            repo = self._versioning_repo
            branches = await repo.list_branches(server_id=query.server_id)
        else:
            async with database.session_factory() as session:
                repo = SQLVersioningRepository(session)
                branches = await repo.list_branches(server_id=query.server_id)
        return [
            {
                "id": b.id,
                "server_id": b.server_id,
                "name": b.name,
                "head_commit_id": b.head_commit_id,
                "created_at": b.created_at.isoformat()
                if hasattr(b.created_at, "isoformat")
                else str(b.created_at),
            }
            for b in branches
        ]
