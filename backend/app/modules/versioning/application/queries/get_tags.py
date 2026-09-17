from __future__ import annotations

from typing import Any

from app.core.exceptions import NotFoundError
from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.repository import VersioningRepository


class GetServerTagsQuery(Query):
    server_id: str


class GetServerTagsHandler(QueryHandler[GetServerTagsQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetServerTagsQuery) -> list[dict[str, Any]]:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.shared.value_objects import ServerId
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None and self._versioning_repo is not None:
            server_repo = self._server_repo
            versioning_repo = self._versioning_repo
            try:
                await server_repo.get(ServerId(query.server_id))
            except Exception as exc:
                raise NotFoundError(f"Server '{query.server_id}' not found") from exc
            tags = await versioning_repo.list_tags(query.server_id)
            return [
                {
                    "id": t.id,
                    "server_id": t.server_id,
                    "name": t.name,
                    "commit_id": t.commit_id,
                    "created_at": t.created_at.isoformat(),
                }
                for t in tags
            ]

        async with database.session_factory() as session:
            server_repo = SQLServerRepository(session)
            versioning_repo = SQLVersioningRepository(session)
            try:
                await server_repo.get(ServerId(query.server_id))
            except Exception as exc:
                raise NotFoundError(f"Server '{query.server_id}' not found") from exc

            tags = await versioning_repo.list_tags(query.server_id)
            return [
                {
                    "id": t.id,
                    "server_id": t.server_id,
                    "name": t.name,
                    "commit_id": t.commit_id,
                    "created_at": t.created_at.isoformat(),
                }
                for t in tags
            ]


class GetServerTagQuery(Query):
    server_id: str
    name: str


class GetServerTagHandler(QueryHandler[GetServerTagQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetServerTagQuery) -> dict[str, Any] | None:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.shared.value_objects import ServerId
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None and self._versioning_repo is not None:
            server_repo = self._server_repo
            versioning_repo = self._versioning_repo
            try:
                await server_repo.get(ServerId(query.server_id))
            except Exception as exc:
                raise NotFoundError(f"Server '{query.server_id}' not found") from exc
            t = await versioning_repo.get_tag(query.server_id, query.name)
            if not t:
                return None
            return {
                "id": t.id,
                "server_id": t.server_id,
                "name": t.name,
                "commit_id": t.commit_id,
                "created_at": t.created_at.isoformat(),
            }

        async with database.session_factory() as session:
            server_repo = SQLServerRepository(session)
            versioning_repo = SQLVersioningRepository(session)
            try:
                await server_repo.get(ServerId(query.server_id))
            except Exception as exc:
                raise NotFoundError(f"Server '{query.server_id}' not found") from exc

            t = await versioning_repo.get_tag(query.server_id, query.name)
            if not t:
                return None
            return {
                "id": t.id,
                "server_id": t.server_id,
                "name": t.name,
                "commit_id": t.commit_id,
                "created_at": t.created_at.isoformat(),
            }
