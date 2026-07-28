from __future__ import annotations

from datetime import datetime

from app.core.query_bus import Query, QueryHandler
from app.modules.plugin.domain.repository import PluginRepository
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.shared.value_objects import ServerId
from app.core.persistence.db import database


class PluginReadModel:
    def __init__(
        self,
        plugin_id: str,
        server_id: str,
        name: str,
        version: str,
        description: str,
        author: str,
        status: str,
        dependencies: list[str],
        installed_at: datetime,
        updated_at: datetime,
    ) -> None:
        self.plugin_id = plugin_id
        self.server_id = server_id
        self.name = name
        self.version = version
        self.description = description
        self.author = author
        self.status = status
        self.dependencies = dependencies
        self.installed_at = installed_at
        self.updated_at = updated_at

    @classmethod
    def from_domain(cls, plugin: object) -> PluginReadModel:
        return cls(
            plugin_id=str(plugin.plugin_id),
            server_id=str(plugin.server_id),
            name=plugin.name,
            version=str(plugin.version),
            description=plugin.description,
            author=plugin.author,
            status=plugin.status.value,
            dependencies=plugin.dependencies,
            installed_at=plugin.installed_at,
            updated_at=plugin.updated_at,
        )


class ListPluginsQuery(Query):
    server_id: str


class ListPluginsHandler(QueryHandler[ListPluginsQuery]):
    async def handle(self, query: ListPluginsQuery) -> list[PluginReadModel]:
        server_id = ServerId(query.server_id)
        async with database.session_factory() as session:
            repo: PluginRepository = SQLPluginRepository(session)
            plugins = await repo.list_by_server(server_id)
            return [PluginReadModel.from_domain(p) for p in plugins]
