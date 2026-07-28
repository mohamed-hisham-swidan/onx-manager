from typing import Any

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import MemoryAllocation
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.core.persistence.unit_of_work import UnitOfWork


class UpdateServerConfigCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str
    properties: dict[str, Any] = {}
    min_memory_mb: int | None = None
    max_memory_mb: int | None = None


class UpdateServerConfigHandler(CommandHandler[UpdateServerConfigCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: UpdateServerConfigCommand) -> CommandResult:
        server_id = ServerId(command.server_id)

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerRepository = SQLServerRepository(uow.session)
            server = await repo.get(server_id)

            if command.properties:
                server.update_properties(**command.properties)
            if command.min_memory_mb is not None or command.max_memory_mb is not None:
                min_mb = command.min_memory_mb or server.memory.min_mb
                max_mb = command.max_memory_mb or server.memory.max_mb
                server.update_memory(MemoryAllocation(min_mb=min_mb, max_mb=max_mb))

            await repo.save(server)
            for event in server.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data={"server_id": command.server_id})
