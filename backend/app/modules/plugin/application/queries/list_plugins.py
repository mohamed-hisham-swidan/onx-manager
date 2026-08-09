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
        source: str = "manual",
        filename: str | None = None,
        pending_deletion: bool = False,
        pending_deletion_requested_at: datetime | None = None,
        external_project_id: str | None = None,
        external_version_id: str | None = None,
        external_url: str | None = None,
        checksum: str | None = None,
        icon_url: str | None = None,
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
        self.source = source
        self.filename = filename
        self.pending_deletion = pending_deletion
        self.pending_deletion_requested_at = pending_deletion_requested_at
        self.external_project_id = external_project_id
        self.external_version_id = external_version_id
        self.external_url = external_url
        self.checksum = checksum
        self.icon_url = icon_url

    @classmethod
    def from_domain(cls, plugin: object) -> PluginReadModel:
        return cls(
            plugin_id=str(plugin.plugin_id),
            server_id=str(plugin.server_id),
            name=plugin.name,
            version=plugin.display_version,
            description=plugin.description,
            author=plugin.author,
            status=plugin.status.value,
            dependencies=plugin.dependencies,
            installed_at=plugin.installed_at,
            updated_at=plugin.updated_at,
            source=plugin.source,
            filename=plugin.filename,
            pending_deletion=plugin.pending_deletion,
            pending_deletion_requested_at=plugin.pending_deletion_requested_at,
            external_project_id=plugin.external_project_id,
            external_version_id=plugin.external_version_id,
            external_url=plugin.external_url,
            checksum=plugin.checksum,
            icon_url=plugin.icon_url,
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
