from __future__ import annotations

import asyncio
import logging

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ServerNotRunningError
from app.core.idempotency import IdempotencyKey
from app.core.identity import IDENTITY
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.server.application.logging_utils import (
    add_timeline_milestone,
    format_event,
    progress_phase,
    shutdown_timeline,
)
from app.modules.server.application.runtime_ownership import _port_is_listening, _wait_for_port_free
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import (
    build_server_handle,
    default_provider_for_platform,
)
from app.modules.server.infrastructure.providers import provider_factory
from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.commands.stop_server")

_PROVIDER_CALL_TIMEOUT: float = 50.0
_FORCE_STOP_TIMEOUT: float = 15.0


def is_stop_confirmed(result: CommandResult | None) -> bool:
    """Return True iff StopServerCommand succeeded with verified runtime & port stop.

    Requires zero warnings/errors.
    """
    if result is None or not result.success or not isinstance(result.data, dict):
        return False
    return (
        result.data.get("stop_confirmed") is True
        and not result.data.get("warnings")
        and not result.data.get("provider_errors")
    )


class StopServerCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    reason: str = ""
    force: bool = False


class StopServerHandler(CommandHandler[StopServerCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: StopServerCommand) -> CommandResult:
        server_id = ServerId(command.server_id)
        sid = str(server_id)

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerRepository = SQLServerRepository(uow.session)
            server = await repo.get(server_id)
            server_name = server.name
            if server.status not in (
                ServerStatus.RUNNING,
                ServerStatus.STARTING,
                ServerStatus.STOPPING,
            ):
                raise ServerNotRunningError(sid)

            if server.status in (ServerStatus.RUNNING, ServerStatus.STARTING):
                server.stop(reason=command.reason)
                await repo.save(server)
                for event in server.collect_events():
                    uow.add_event(event)
                    logger.info("EVENT %s", format_event(event, server_name))
                await uow.commit()

        logger.info(
            'Server "%s" stopping — reason="%s" server_id=%s',
            server_name,
            command.reason,
            sid,
        )

        provider_errors: list[str] = []
        runtime_verified = False
        port_verified = True
        last_status: ServerRuntimeStatus | None = None

        with shutdown_timeline(server_name, sid):
            add_timeline_milestone(None, "Stopping supervisor", server_name, sid)
            await RuntimeSupervisor.stop_for(sid)
            add_timeline_milestone(None, "Supervisor stopped", server_name, sid)

            provider_type = (
                server.runtime.provider
                if server.runtime and server.runtime.provider
                else default_provider_for_platform()
            )
            provider = provider_factory.get(provider_type)
            server_dir = (
                server.deployment.server_directory() if server.deployment else None
            )
            handle = build_server_handle(server, provider_type, server_dir=server_dir)

            has_runtime_handle = bool(
                server.runtime
                and server.runtime.external_id
            )

            if not has_runtime_handle:
                provider_errors.append("Cannot verify stop: server has no runtime handle")
                runtime_verified = False
            else:
                if command.force:
                    add_timeline_milestone(None, "Provider stop (force)", server_name, sid)
                    with progress_phase("Force stop", 1, 1, server_name, sid):
                        try:
                            await asyncio.wait_for(
                                provider.stop(handle, force=True),
                                timeout=_FORCE_STOP_TIMEOUT,
                            )
                        except Exception as exc:
                            provider_errors.append(f"Force stop failed: {exc}")
                else:
                    try:
                        add_timeline_milestone(None, "Provider stop (graceful)", server_name, sid)
                        with progress_phase("Graceful stop", 1, 2, server_name, sid):
                            await asyncio.wait_for(
                                provider.stop(handle),
                                timeout=_PROVIDER_CALL_TIMEOUT,
                            )
                    except TimeoutError:
                        logger.warning(
                            'Server "%s" provider stop timed out — forcing stop server_id=%s',
                            server_name,
                            sid,
                        )
                        provider_errors.append(
                            f"Stop timed out after {_PROVIDER_CALL_TIMEOUT:.0f}s, force applied"
                        )
                        add_timeline_milestone(None, "Provider stop (force)", server_name, sid)
                        with progress_phase("Force stop", 2, 2, server_name, sid):
                            try:
                                await asyncio.wait_for(
                                    provider.stop(handle, force=True),
                                    timeout=_FORCE_STOP_TIMEOUT,
                                )
                            except Exception as exc:
                                provider_errors.append(f"Force stop failed: {exc}")
                    except Exception as exc:
                        provider_errors.append(f"Provider stop failed: {exc}")
                        add_timeline_milestone(
                            None, "Provider stop (force after error)", server_name, sid
                        )
                        with progress_phase("Force stop (after error)", 2, 2, server_name, sid):
                            try:
                                await asyncio.wait_for(
                                    provider.stop(handle, force=True),
                                    timeout=_FORCE_STOP_TIMEOUT,
                                )
                            except Exception as exc2:
                                provider_errors.append(f"Force stop also failed: {exc2}")

                try:
                    last_status = await asyncio.wait_for(provider.status(handle), timeout=5)
                    if last_status != ServerRuntimeStatus.STOPPED:
                        runtime_verified = False
                        if last_status == ServerRuntimeStatus.RUNNING:
                            logger.warning(
                                'Server "%s" still running after stop (status=%s server_id=%s)',
                                server_name,
                                last_status.value,
                                sid,
                            )
                            provider_errors.append(f"Runtime still {last_status.value} after stop")
                        else:
                            logger.warning(
                                'Server "%s" stopped with unexpected status '
                                "(status=%s server_id=%s)",
                                server_name,
                                last_status.value,
                                sid,
                            )
                            provider_errors.append(
                                f"Runtime status is {last_status.value} after stop"
                            )
                    else:
                        runtime_verified = True
                        add_timeline_milestone(None, "Provider confirmed stopped", server_name, sid)
                except Exception as exc:
                    runtime_verified = False
                    provider_errors.append(f"Provider status check failed after stop: {exc}")

            stop_port = (
                server.properties.port.value
                if hasattr(server, "properties")
                and hasattr(server.properties, "port")
                and hasattr(server.properties.port, "value")
                else (
                    server.runtime.port
                    if server.runtime and server.runtime.port
                    else 0
                )
            )

            if stop_port > 0:
                if _port_is_listening(stop_port):
                    released = _wait_for_port_free(stop_port, timeout=5.0)
                    if released:
                        port_verified = True
                        logger.info(
                            'Port %d released after stop — server="%s" server_id=%s',
                            stop_port,
                            server_name,
                            sid,
                        )
                    else:
                        port_verified = False
                        logger.warning(
                            'Port %d still listening after stop — server="%s" server_id=%s',
                            stop_port,
                            server_name,
                            sid,
                        )
                        provider_errors.append(f"Port {stop_port} still listening after stop")
                else:
                    port_verified = True
                    logger.info(
                        'Port %d already free — server="%s" server_id=%s',
                        stop_port,
                        server_name,
                        sid,
                    )

            stop_confirmed = (
                has_runtime_handle
                and runtime_verified
                and port_verified
                and len(provider_errors) == 0
            )

            if stop_confirmed:
                if server_dir:
                    from app.modules.server.infrastructure.providers.docker import (
                        _remove_persisted_rcon_port,
                    )

                    _remove_persisted_rcon_port(server_dir)
                async with UnitOfWork(self._event_bus) as uow:
                    repo = SQLServerRepository(uow.session)
                    server = await repo.get(server_id)
                    server.mark_stopped()
                    await repo.save(server)
                    for event in server.collect_events():
                        uow.add_event(event)
                        logger.info("EVENT %s", format_event(event, server_name))
                    await uow.commit()

                add_timeline_milestone(None, "Server marked stopped", server_name, sid)
                logger.info('Server "%s" stopped — server_id=%s', server_name, sid)
                return CommandResult(
                    success=True,
                    data={
                        "server_id": sid,
                        "status": "stopped",
                        "stop_confirmed": True,
                        "runtime_verified": True,
                        "port_verified": True,
                        "warnings": [],
                        "provider_errors": [],
                    },
                )
            elif last_status == ServerRuntimeStatus.RUNNING or not port_verified:
                async with UnitOfWork(self._event_bus) as uow:
                    repo = SQLServerRepository(uow.session)
                    server = await repo.get(server_id)
                    if server.status == ServerStatus.STOPPING:
                        server.revert_to_running()
                        await repo.save(server)
                        for event in server.collect_events():
                            uow.add_event(event)
                        await uow.commit()

                active_sup = RuntimeSupervisor.get_for(sid)
                if not active_sup or not active_sup.is_running:
                    try:
                        RuntimeSupervisor.start_for(
                            server=server,
                            provider=provider,
                            handle=handle,
                            repo_get=lambda s_id: sql_get_server(s_id),
                            repo_save=lambda s: sql_save_server(s, self._event_bus),
                        )
                    except Exception as exc:
                        logger.warning("Failed to re-attach supervisor for %s: %s", sid, exc)

                logger.warning(
                    'Server "%s" stop failed and reverted to running — server_id=%s',
                    server_name,
                    sid,
                )
                return CommandResult(
                    success=False,
                    error="; ".join(provider_errors),
                    error_code="SERVER_STOP_FAILED",
                    data={
                        "server_id": sid,
                        "status": "running",
                        "stop_confirmed": False,
                        "runtime_verified": runtime_verified,
                        "port_verified": port_verified,
                        "warnings": provider_errors,
                        "provider_errors": provider_errors,
                    },
                )
            else:
                async with UnitOfWork(self._event_bus) as uow:
                    repo = SQLServerRepository(uow.session)
                    server = await repo.get(server_id)
                    if server.status == ServerStatus.STOPPING:
                        server.mark_stop_unknown(reason="; ".join(provider_errors))
                        await repo.save(server)
                        for event in server.collect_events():
                            uow.add_event(event)
                        await uow.commit()

                logger.warning(
                    'Server "%s" stop unconfirmed (remains stopping) — server_id=%s',
                    server_name,
                    sid,
                )
                return CommandResult(
                    success=False,
                    error="; ".join(provider_errors),
                    error_code="SERVER_STOP_UNCONFIRMED",
                    data={
                        "server_id": sid,
                        "status": "stopping",
                        "stop_confirmed": False,
                        "runtime_verified": runtime_verified,
                        "port_verified": port_verified,
                        "warnings": provider_errors,
                        "provider_errors": provider_errors,
                    },
                )


async def sql_get_server(sid: ServerId) -> Server:
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        return await repo.get(sid)


async def sql_save_server(server: Server, event_bus: EventBus) -> None:
    from app.core.persistence.unit_of_work import UnitOfWork
    from app.modules.server.infrastructure.repository import SQLServerRepository

    async with UnitOfWork(event_bus) as uow:
        repo = SQLServerRepository(uow.session)
        await repo.save(server)
        for event in server.collect_events():
            uow.add_event(event)
        await uow.commit()
