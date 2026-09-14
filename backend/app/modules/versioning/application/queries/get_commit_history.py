from __future__ import annotations

from typing import Any

from app.core.query_bus import Query, QueryHandler
from app.modules.versioning.domain.repository import VersioningRepository


class GetCommitHistoryQuery(Query):
    server_id: str
    branch_id: str | None = None
    limit: int = 50


class GetCommitHistoryHandler(QueryHandler[GetCommitHistoryQuery]):
    def __init__(self, versioning_repo: VersioningRepository | None = None) -> None:
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetCommitHistoryQuery) -> list[dict[str, Any]]:
        from app.core.persistence.db import database
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._versioning_repo is not None:
            repo = self._versioning_repo
            commits = await repo.list_commits(
                server_id=query.server_id,
                branch_id=query.branch_id,
                limit=query.limit,
            )
        else:
            async with database.session_factory() as session:
                repo = SQLVersioningRepository(session)
                commits = await repo.list_commits(
                    server_id=query.server_id,
                    branch_id=query.branch_id,
                    limit=query.limit,
                )
        return [
            {
                "id": c.id,
                "server_id": c.server_id,
                "branch_id": c.branch_id,
                "parent_commit_id": c.parent_commit_id,
                "author_id": c.author_id,
                "message": c.message,
                "manifest": c.manifest.to_dict(),
                "world_snapshot_id": c.world_snapshot_id,
                "created_at": c.created_at.isoformat()
                if hasattr(c.created_at, "isoformat")
                else str(c.created_at),
            }
            for c in commits
        ]
