from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.server.application.read_models import ServerDetailReadModel
from app.modules.server.domain.aggregate import ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.providers import ServerHandle, provider_factory
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId


class GetServerQuery(Query):
    server_id: str


class GetServerHandler(QueryHandler[GetServerQuery]):
    async def handle(self, query: GetServerQuery) -> ServerDetailReadModel | None:
        async with database.session_factory() as session:
            repo: ServerRepository = SQLServerRepository(session)
            server = await repo.get(ServerId(query.server_id))
            if not server:
                return None
            if server.status == ServerStatus.RUNNING and server.runtime:
                try:
                    provider = provider_factory.get(server.runtime.provider)
                    handle = ServerHandle(
                        provider=server.runtime.provider,
                        server_id=str(server.id),
                        external_id=server.runtime.external_id or f"onx-{server.id}",
                    )
                    live_addr = await provider.get_address(handle)
                    if live_addr and live_addr != server.runtime.host:
                        server.runtime.host = live_addr
                        await repo.save(server)
                        await session.commit()
                except Exception:
                    pass
            return ServerDetailReadModel.from_domain(server)

