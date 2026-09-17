from __future__ import annotations

from typing import Any

from app.core.exceptions import NotFoundError
from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.diff import diff_commits
from app.modules.versioning.domain.repository import VersioningRepository


class DiffCommitsQuery(Query):
    server_id: str
    from_commit_id: str
    to_commit_id: str


class DiffCommitsHandler(QueryHandler[DiffCommitsQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: DiffCommitsQuery) -> dict[str, Any]:
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
        query: DiffCommitsQuery,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> dict[str, Any]:
        from app.modules.shared.value_objects import ServerId

        try:
            await server_repo.get(ServerId(query.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{query.server_id}' not found") from exc

        commit_a = await versioning_repo.get_commit(query.from_commit_id)
        if commit_a is None or commit_a.server_id != query.server_id:
            raise NotFoundError(
                f"From commit '{query.from_commit_id}' not found on server '{query.server_id}'"
            )

        commit_b = await versioning_repo.get_commit(query.to_commit_id)
        if commit_b is None or commit_b.server_id != query.server_id:
            raise NotFoundError(
                f"To commit '{query.to_commit_id}' not found on server '{query.server_id}'"
            )

        diff = diff_commits(commit_a, commit_b)
        return diff.to_dict()
