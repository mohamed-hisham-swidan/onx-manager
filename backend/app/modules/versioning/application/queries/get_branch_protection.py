from __future__ import annotations

from typing import Any

from app.core.exceptions import NotFoundError
from app.core.query_bus import Query, QueryHandler
from app.modules.versioning.domain.repository import VersioningRepository


class GetBranchProtectionQuery(Query):
    server_id: str
    branch_name: str


class GetBranchProtectionHandler(QueryHandler[GetBranchProtectionQuery]):
    def __init__(self, versioning_repo: VersioningRepository | None = None) -> None:
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetBranchProtectionQuery) -> dict[str, Any]:
        from app.core.persistence.db import database
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._versioning_repo is not None:
            return await self._execute(query, self._versioning_repo)

        async with database.session_factory() as session:
            versioning_repo = SQLVersioningRepository(session)
            return await self._execute(query, versioning_repo)

    async def _execute(
        self,
        query: GetBranchProtectionQuery,
        versioning_repo: VersioningRepository,
    ) -> dict[str, Any]:
        branch = await versioning_repo.get_branch_by_name(query.server_id, query.branch_name)
        if branch is None:
            raise NotFoundError(
                f"Branch '{query.branch_name}' not found on server '{query.server_id}'"
            )

        return {
            "server_id": query.server_id,
            "branch_name": branch.name,
            "is_protected": branch.is_protected,
            "policy": branch.protection_policy.to_dict() if branch.protection_policy else None,
        }
