import asyncio
import contextlib
import logging
from typing import Any

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.exceptions import ServerNotFoundError
from app.core.fs_utils import assert_inside_root
from app.core.idempotency import IdempotencyKey
from app.core.identity import IDENTITY
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.server.application.commands.stop_server import (
    StopServerCommand,
    StopServerHandler,
)
from app.modules.server.application.runtime_ownership import _port_is_listening
from app.modules.server.application.services.installer_provisioner import ProvisioningRegistry
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.aggregate import ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import (
    build_server_handle,
    default_provider_for_platform,
)
from app.modules.server.infrastructure.fs import local_fs
from app.modules.server.infrastructure.providers import (
    provider_factory as default_provider_factory,
)
from app.modules.server.infrastructure.providers.base import (
    ProviderFactory,
    ServerRuntimeStatus,
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
            handle = build_server_handle(server, provider_type, server_dir=server_dir)
            if server_dir and "root_path" not in handle.metadata:
                handle.metadata["root_path"] = server_dir

        # 2. Cancel and await provisioning if server is currently PROVISIONING
        if server_status == ServerStatus.PROVISIONING:
            logger.info("Server %s is PROVISIONING — cancelling provisioning task", sid)
            await ProvisioningRegistry.cancel_and_wait(sid, timeout=15.0)

        # 3. Stop running server if needed so JVM / supervisor processes are not orphaned (F050)
        if server_status in (ServerStatus.RUNNING, ServerStatus.STARTING, ServerStatus.STOPPING):
            try:
                stop_handler = StopServerHandler(self._event_bus)
                await stop_handler.handle(
                    StopServerCommand(
                        server_id=command.server_id,
                        reason="Server deletion",
                        force=True,
                    )
                )
            except Exception as e:
                logger.warning(
                    "Failed to stop server %s before delete: %s",
                    command.server_id,
                    e,
                )

        with contextlib.suppress(Exception):
            await RuntimeSupervisor.stop_for(sid)

        # 4. Resolve provider safely
        provider: Any = None
        provider_error: Exception | None = None
        try:
            factory = self._provider_factory or default_provider_factory
            provider = factory.get(provider_type)
        except Exception as e:
            provider_error = e
            logger.warning(
                'Failed to resolve provider for server "%s" (provider=%s): %s',
                server_name,
                provider_type,
                e,
            )

        if provider is None and server_status in (
            ServerStatus.RUNNING,
            ServerStatus.STARTING,
            ServerStatus.STOPPING,
        ):
            return CommandResult(
                success=False,
                error=(
                    f"Cannot delete server: provider {provider_type} unavailable: "
                    f"{provider_error}"
                ),
                error_code="PROVIDER_UNAVAILABLE",
            )

        if provider is not None:
            # 5. Confirm container/process is NOT running BEFORE calling destroy (Spec F6)
            runtime_running = False
            try:
                status = await provider.status(handle)
                if status == ServerRuntimeStatus.RUNNING:
                    runtime_running = True
            except Exception:
                pass

            if runtime_running:
                return CommandResult(
                    success=False,
                    error="Cannot delete server: runtime process/container could not be stopped",
                    error_code="DELETE_STOP_NOT_CONFIRMED",
                )

        # 6. Re-check game port after stop confirmed
        port_val = handle.metadata.get("port") if handle and handle.metadata else None
        if port_val is not None:
            try:
                if _port_is_listening(int(port_val)):
                    return CommandResult(
                        success=False,
                        error=f"Cannot delete server: port {port_val} is still occupied",
                        error_code="DELETE_STOP_NOT_CONFIRMED",
                    )
            except Exception:
                pass

        # 7. Teardown provider resources (containers, tmux sessions, process trees, caches)
        if provider is not None:
            try:
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

        with contextlib.suppress(Exception):
            from app.modules.versioning.application import cleanup_server_materializations

            await cleanup_server_materializations(sid, self._event_bus)

        if server_dir:
            try:
                assert_inside_root(server_dir, AppSettings().servers_data_dir)
                local_fs.delete_dir(server_dir)
                logger.info(
                    'Server "%s" filesystem directory removed — path=%s',
                    server_name,
                    server_dir,
                )
            except Exception as exc:
                logger.exception(
                    'Failed to remove filesystem directory for server "%s" — path=%s server_id=%s',
                    server_name,
                    server_dir,
                    command.server_id,
                )
                return CommandResult(
                    success=False,
                    error=(
                        "Server record deleted, but filesystem directory could not be removed: "
                        f"{exc}. Manual cleanup required."
                    ),
                    error_code="FILESYSTEM_CLEANUP_FAILED",
                    details={
                        "server_id": command.server_id,
                        "leftover_path": server_dir,
                        "cleanup_hint": (
                            "The server database record was deleted, but the directory "
                            f"'{server_dir}' could not be removed from disk. This may be "
                            "caused by file permissions or active file locks. "
                            "Inspect and remove the directory on the host to free disk space."
                        ),
                    },
                )

        return CommandResult(success=True, data={"server_id": command.server_id})
