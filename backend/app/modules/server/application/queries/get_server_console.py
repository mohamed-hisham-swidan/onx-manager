from app.core.exceptions import ProviderError
from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.server.domain.aggregate import ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId

RUNNING_STATUSES = {ServerStatus.RUNNING, ServerStatus.STARTING}


class GetServerConsoleQuery(Query):
    server_id: str
    tail: int = 100


class ConsoleReadModel:
    def __init__(self, server_id: str, lines: list[str]) -> None:
        self.server_id = server_id
        self.lines = lines


class GetServerConsoleHandler(QueryHandler[GetServerConsoleQuery]):
    async def handle(self, query: GetServerConsoleQuery) -> ConsoleReadModel:
        async with database.session_factory() as session:
            repo: ServerRepository = SQLServerRepository(session)
            server = await repo.get(ServerId(query.server_id))

            if (
                not server.runtime
                or not server.runtime.external_id
                or server.status not in RUNNING_STATUSES
            ):
                # Server not running — return empty list (no crash log lines stored in RuntimeInfo)
                return ConsoleReadModel(server_id=query.server_id, lines=[])

            from app.modules.server.domain.value_objects import default_provider_for_platform
            from app.modules.server.infrastructure.providers import provider_factory

            provider_type = server.runtime.provider or default_provider_for_platform()
            provider = provider_factory.get(provider_type)
            from app.modules.server.infrastructure.providers.base import ServerHandle

            handle = ServerHandle(
                provider=provider_type,
                server_id=str(server.id),
                external_id=server.runtime.external_id,
            )
            try:
                lines = await provider.console(handle, tail=query.tail)
            except ProviderError:
                return ConsoleReadModel(server_id=query.server_id, lines=[])
            return ConsoleReadModel(server_id=query.server_id, lines=lines)
