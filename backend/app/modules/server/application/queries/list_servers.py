from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.server.application.read_models import ServerReadModel
from app.modules.server.domain.repository import ServerFilters, ServerRepository
from app.modules.server.infrastructure.repository import SQLServerRepository


class ListServersQuery(Query):
    status: str | None = None
    group_id: str | None = None
    name_search: str | None = None
    minecraft_version: str | None = None


class ListServersHandler(QueryHandler[ListServersQuery]):
    async def handle(self, query: ListServersQuery) -> list[ServerReadModel]:
        filters = ServerFilters(
            status=query.status,
            group_id=query.group_id,
            name_search=query.name_search,
            minecraft_version=query.minecraft_version,
        )
        async with database.session_factory() as session:
            repo: ServerRepository = SQLServerRepository(session)
            servers = await repo.list(filters)
            return [ServerReadModel.from_domain(s) for s in servers]
