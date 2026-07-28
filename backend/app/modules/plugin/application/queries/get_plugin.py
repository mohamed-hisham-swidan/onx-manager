from app.core.query_bus import Query, QueryHandler
from app.modules.plugin.application.queries.list_plugins import PluginReadModel
from app.modules.plugin.domain.repository import PluginRepository
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.shared.value_objects import PluginId
from app.core.persistence.db import database


class GetPluginQuery(Query):
    plugin_id: str


class GetPluginHandler(QueryHandler[GetPluginQuery]):
    async def handle(self, query: GetPluginQuery) -> PluginReadModel:
        async with database.session_factory() as session:
            repo: PluginRepository = SQLPluginRepository(session)
            plugin = await repo.get(PluginId(query.plugin_id))
            return PluginReadModel.from_domain(plugin)
