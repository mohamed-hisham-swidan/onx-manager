import asyncio
import contextlib
import logging

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ServerNotFoundError
from app.core.idempotency import IdempotencyKey
from app.core.identity import IDENTITY
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.server.application.commands.stop_server import (
    StopServerCommand,
    StopServerHandler,
)
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.aggregate import ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import default_provider_for_platform
from app.modules.server.infrastructure.fs import local_fs
from app.modules.server.infrastructure.providers import (
    provider_factory as default_provider_factory,
)
from app.modules.server.infrastructure.providers.base import (
    ProviderFactory,
    ServerHandle,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.commands.delete_server")

DESTROY_TIMEOUT_SECONDS: float = 10.0


class DeleteServerCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str


class DeleteServerHandler(CommandHandler[DeleteServerCommand]):
    def __init__(
        self,
        event_bus: EventBus,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._provider_factory = provider_factory

    async def handle(self, command: DeleteServerCommand) -> CommandResult:
        server_id = ServerId(command.server_id)
        sid = str(server_id)

        # 1. Check server existence and current status
        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerRepository = SQLServerRepository(uow.session)

            try:
                server = await repo.get(server_id)
            except ServerNotFoundError:
                logger.warning(
                    "Delete called for nonexistent server %s — returning 404",
                    command.server_id,
                )
                return CommandResult(
                    success=False,
                    error=f"Server {command.server_id} not found",
                    error_code="NOT_FOUND",
                )
            server_status = server.status
            server_name = server.name
            server_dir = server.deployment.server_directory() if server.deployment else None
            provider_type = (
                server.runtime.provider
                if server.runtime and server.runtime.provider
                else default_provider_for_platform()
            )
            external_id = (
                server.runtime.external_id
                if server.runtime and server.runtime.external_id
                else f"{IDENTITY.temp_prefix_new}{sid}"
            )

        handle = ServerHandle(
            provider=provider_type,
            server_id=sid,
            external_id=external_id,
            metadata={"server_name": server_name, "root_path": server_dir},
        )

        # 2. Stop running server if needed so JVM / supervisor processes are not orphaned (F050)
        if server_status in (ServerStatus.RUNNING, ServerStatus.STARTING):
            try:
                stop_handler = StopServerHandler(self._event_bus)
                await stop_handler.handle(
                    StopServerCommand(server_id=command.server_id, reason="Server deletion")
                )
            except Exception as e:
                logger.warning(
                    "Failed to gracefully stop server %s before delete: %s",
                    command.server_id,
                    e,
                )

        with contextlib.suppress(Exception):
            await RuntimeSupervisor.stop_for(sid)

        # 3. Teardown provider resources (containers, tmux sessions, process trees, caches)
        factory = self._provider_factory or default_provider_factory
        try:
            provider = factory.get(provider_type)
            await asyncio.wait_for(
                provider.destroy(handle),
                timeout=DESTROY_TIMEOUT_SECONDS,
            )
            logger.info(
                'Server "%s" provider resources destroyed — provider=%s server_id=%s',
                server_name,
                provider_type,
                sid,
            )
        except TimeoutError:
            logger.warning(
                'Server "%s" provider destroy timed out after %ss — provider=%s server_id=%s',
                server_name,
                DESTROY_TIMEOUT_SECONDS,
                provider_type,
                sid,
            )
        except Exception as e:
            logger.warning(
                'Failed to destroy provider resources for server "%s" (provider=%s): %s',
                server_name,
                provider_type,
                e,
            )

        # 4. Mark deleted, delete record from repo and collect events
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLServerRepository(uow.session)
            try:
                server = await repo.get(server_id)
            except ServerNotFoundError:
                return CommandResult(success=True, data={"server_id": command.server_id})

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
            server_name,
            command.server_id,
        )

        if server_dir:
            try:
                local_fs.delete_dir(server_dir)
                logger.info(
                    'Server "%s" filesystem directory removed — path=%s',
                    server_name,
                    server_dir,
                )
            except Exception:
                logger.exception(
                    'Failed to remove filesystem directory for server "%s" — path=%s server_id=%s',
                    server_name,
                    server_dir,
                    command.server_id,
                )

        return CommandResult(success=True, data={"server_id": command.server_id})
