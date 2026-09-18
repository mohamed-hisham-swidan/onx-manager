from __future__ import annotations

from typing import Any

from app.core.exceptions import NotFoundError
from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.repository import ServerRepository
from app.modules.shared.value_objects import ServerId
from app.modules.versioning.domain.entities import TestDefinition
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import BotTech, PlacementMode


def _serialize_test_definition(d: TestDefinition) -> dict[str, Any]:
    return {
        "id": d.id,
        "server_id": d.server_id,
        "name": d.name,
        "description": d.description,
        "server_type": d.server_type,
        "bot_technology": (
            d.bot_technology.value
            if isinstance(d.bot_technology, BotTech)
            else d.bot_technology
        ),
        "bot_count": d.bot_count,
        "duration_seconds": d.duration_seconds,
        "join_stagger_seconds": d.join_stagger_seconds,
        "connect_grace_seconds": d.connect_grace_seconds,
        "placement_mode": (
            d.placement_mode.value
            if isinstance(d.placement_mode, PlacementMode)
            else d.placement_mode
        ),
        "assertion_rules": d.assertion_rules,
        "timeout_seconds": d.timeout_seconds,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }


class ListTestDefinitionsQuery(Query):
    server_id: str


class ListTestDefinitionsHandler(QueryHandler[ListTestDefinitionsQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: ListTestDefinitionsQuery) -> list[dict[str, Any]]:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None and self._versioning_repo is not None:
            server_repo = self._server_repo
            versioning_repo = self._versioning_repo
            try:
                await server_repo.get(ServerId(query.server_id))
            except Exception as exc:
                raise NotFoundError(f"Server '{query.server_id}' not found") from exc
            definitions = await versioning_repo.list_test_definitions(query.server_id)
            return [_serialize_test_definition(d) for d in definitions]

        async with database.session_factory() as session:
            server_repo = SQLServerRepository(session)
            versioning_repo = SQLVersioningRepository(session)
            try:
                await server_repo.get(ServerId(query.server_id))
            except Exception as exc:
                raise NotFoundError(f"Server '{query.server_id}' not found") from exc

            definitions = await versioning_repo.list_test_definitions(query.server_id)
            return [_serialize_test_definition(d) for d in definitions]


class GetTestDefinitionQuery(Query):
    server_id: str
    definition_id: str


class GetTestDefinitionHandler(QueryHandler[GetTestDefinitionQuery]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, query: GetTestDefinitionQuery) -> dict[str, Any] | None:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None and self._versioning_repo is not None:
            server_repo = self._server_repo
            versioning_repo = self._versioning_repo
            try:
                await server_repo.get(ServerId(query.server_id))
            except Exception as exc:
                raise NotFoundError(f"Server '{query.server_id}' not found") from exc
            definition = await versioning_repo.get_test_definition(query.definition_id)
            if definition is None or definition.server_id != query.server_id:
                return None
            return _serialize_test_definition(definition)

        async with database.session_factory() as session:
            server_repo = SQLServerRepository(session)
            versioning_repo = SQLVersioningRepository(session)
            try:
                await server_repo.get(ServerId(query.server_id))
            except Exception as exc:
                raise NotFoundError(f"Server '{query.server_id}' not found") from exc

            definition = await versioning_repo.get_test_definition(query.definition_id)
            if definition is None or definition.server_id != query.server_id:
                return None
            return _serialize_test_definition(definition)
