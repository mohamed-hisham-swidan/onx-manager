from __future__ import annotations

import asyncio
import logging

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.exceptions import ServerNotRunningError
from app.modules.server.application.logging_utils import (
    add_timeline_milestone,
    format_event,
    progress_phase,
    shutdown_timeline,
)
from app.modules.server.application.runtime_ownership import _port_is_listening, _wait_for_port_free
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.aggregate import ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.providers import provider_factory
from app.modules.server.infrastructure.providers.base import ServerHandle, ServerRuntimeStatus
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.core.persistence.unit_of_work import UnitOfWork

from app.core.identity import IDENTITY

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.commands.stop_server")


class StopServerCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str
    reason: str = ""


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
            if server.status not in (ServerStatus.RUNNING, ServerStatus.STARTING):
                raise ServerNotRunningError(sid)
            server.stop(reason=command.reason)
            await repo.save(server)
            for event in server.collect_events():
                uow.add_event(event)
                logger.info("EVENT %s", format_event(event, server_name))
            await uow.commit()

        logger.info(
            'Server "%s" stopping — reason="%s" server_id=%s',
            server_name, command.reason, sid,
        )

        provider_errors: list[str] = []

        with shutdown_timeline(server_name, sid):
            add_timeline_milestone(None, "Stopping supervisor", server_name, sid)
            await RuntimeSupervisor.stop_for(sid)
            add_timeline_milestone(None, "Supervisor stopped", server_name, sid)

            if server.runtime and server.runtime.external_id:
                provider = provider_factory.get(server.runtime.provider)
                handle = ServerHandle(
                    provider=server.runtime.provider,
                    server_id=sid,
                    external_id=server.runtime.external_id,
                    metadata={"server_name": server_name},
                )

                try:
                    add_timeline_milestone(None, "Provider stop (graceful)", server_name, sid)
                    with progress_phase("Graceful stop", 1, 2, server_name, sid):
                        await asyncio.wait_for(provider.stop(handle), timeout=15)
                except TimeoutError:
                    logger.warning(
                        'Server "%s" provider stop timed out — forcing stop server_id=%s',
                        server_name, sid,
                    )
                    provider_errors.append("Stop timed out after 15s, force applied")
                    add_timeline_milestone(None, "Provider stop (force)", server_name, sid)
                    with progress_phase("Force stop", 2, 2, server_name, sid):
                        try:
                            await asyncio.wait_for(provider.stop(handle, force=True), timeout=10)
                        except Exception as exc:
                            provider_errors.append(f"Force stop failed: {exc}")
                except Exception as exc:
                    provider_errors.append(f"Provider stop failed: {exc}")
                    add_timeline_milestone(None, "Provider stop (force after error)", server_name, sid)
                    with progress_phase("Force stop (after error)", 2, 2, server_name, sid):
                        try:
                            await asyncio.wait_for(provider.stop(handle, force=True), timeout=10)
                        except Exception as exc2:
                            provider_errors.append(f"Force stop also failed: {exc2}")

                try:
                    status = await asyncio.wait_for(provider.status(handle), timeout=5)
                    if status != ServerRuntimeStatus.STOPPED:
                        logger.warning(
                            'Server "%s" still running after stop (status=%s server_id=%s)',
                            server_name, status.value, sid,
                        )
                        provider_errors.append(f"Runtime still {status.value} after stop")
                    else:
                        add_timeline_milestone(None, "Provider confirmed stopped", server_name, sid)
                except Exception:
                    pass

                server_port = server.properties.port.value if hasattr(server.properties, "port") else 25565
                if _port_is_listening(server_port):
                    released = _wait_for_port_free(server_port, timeout=5.0)
                    if released:
                        logger.info(
                            'Port %d released after stop — server="%s" server_id=%s',
                            server_port, server_name, sid,
                        )
                    else:
                        logger.warning(
                            'Port %d still listening after stop — server="%s" server_id=%s',
                            server_port, server_name, sid,
                        )
                        provider_errors.append(f"Port {server_port} still listening after stop")
                else:
                    logger.info(
                        'Port %d already free — server="%s" server_id=%s',
                        server_port, server_name, sid,
                    )

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

        logger.info(
            'Server "%s" stopped — server_id=%s',
            server_name, sid,
        )

        result_data: dict = {"server_id": command.server_id}
        if provider_errors:
            result_data["warnings"] = provider_errors
            logger.warning(
                'Server "%s" stop had %d issues — %s server_id=%s',
                server_name, len(provider_errors),
                "; ".join(provider_errors), sid,
            )

        return CommandResult(success=True, data=result_data)
