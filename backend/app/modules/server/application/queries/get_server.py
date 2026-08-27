from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.server.application.read_models import ServerDetailReadModel
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId


class GetServerQuery(Query):
    server_id: str


class GetServerHandler(QueryHandler[GetServerQuery]):
    async def handle(self, query: GetServerQuery) -> ServerDetailReadModel | None:
        async with database.session_factory() as session:
            repo: ServerRepository = SQLServerRepository(session)
            server = await repo.get(ServerId(query.server_id))
            return ServerDetailReadModel.from_domain(server)
