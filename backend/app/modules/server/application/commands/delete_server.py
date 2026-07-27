import logging

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ServerNotFoundError
from app.core.idempotency import IdempotencyKey
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.fs import local_fs
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.storage.unit_of_work import UnitOfWork

logger = logging.getLogger("mcs.commands.delete_server")


class DeleteServerCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str


class DeleteServerHandler(CommandHandler[DeleteServerCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: DeleteServerCommand) -> CommandResult:
        server_id = ServerId(command.server_id)

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerRepository = SQLServerRepository(uow.session)

            try:
                server = await repo.get(server_id)
            except ServerNotFoundError:
                logger.warning(
                    'Delete called for nonexistent server %s — returning 404',
                    command.server_id,
                )
                return CommandResult(
                    success=False,
                    error=f"Server {command.server_id} not found",
                    error_code="NOT_FOUND",
                )

            server_dir: str | None = None
            if server.deployment:
                server_dir = server.deployment.server_directory()

            server_name = server.name
            server.mark_deleted()
            await repo.delete(server_id)
            for event in server.collect_events():
                uow.add_event(event)
            await uow.commit()

        logger.info(
            'Server "%s" deleted — server_id=%s',
            server_name, command.server_id,
        )

        if server_dir:
            try:
                local_fs.delete_dir(server_dir)
                logger.info(
                    'Server "%s" filesystem directory removed — path=%s',
                    server_name, server_dir,
                )
            except Exception:
                logger.exception(
                    'Failed to remove filesystem directory for server "%s" — path=%s server_id=%s',
                    server_name, server_dir, command.server_id,
                )

        return CommandResult(success=True, data={"server_id": command.server_id})
