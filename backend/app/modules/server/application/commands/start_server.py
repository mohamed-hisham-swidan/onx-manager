from __future__ import annotations

import asyncio
import logging

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.modules.server.application.logging_utils import (
    add_timeline_milestone,
    format_event,
    progress_phase,
    startup_timeline,
)
from app.modules.server.application.runtime_ownership import (
    RuntimeOwnershipManager,
    _port_is_listening,
    _wait_for_port_free,
)
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.providers import provider_factory
from app.modules.server.infrastructure.providers.base import ServerHandle
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.storage.unit_of_work import UnitOfWork

logger = logging.getLogger("mcs.commands.start_server")


class StartServerCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str


class StartServerHandler(CommandHandler[StartServerCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: StartServerCommand) -> CommandResult:
        server_id = ServerId(command.server_id)
        sid = str(server_id)

        active_supervisor = RuntimeSupervisor.get_for(sid)
        if active_supervisor and active_supervisor.is_running:
            logger.warning(
                "Server has an active supervisor — stopping it first server_id=%s",
                sid,
            )
            await RuntimeSupervisor.stop_for(sid)

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerRepository = SQLServerRepository(uow.session)
            server = await repo.get(server_id)

            if server.deployment is None:
                return CommandResult(
                    success=False,
                    error="Server has no deployment. Configure install_dir or set up a deployment path.",
                    error_code="NO_DEPLOYMENT",
                )

            if server.runtime and server.runtime.external_id:
                logger.warning(
                    'Server "%s" has stale runtime handle "%s" — cleaning up before start server_id=%s',
                    server.name, server.runtime.external_id, sid,
                )

            provider_type = server.runtime.provider if server.runtime else "local"
            provider = provider_factory.get(provider_type)
            server.start()
            await repo.save(server)
            for event in server.collect_events():
                uow.add_event(event)
                logger.info("EVENT %s", format_event(event, server.name))
            await uow.commit()

        server_name = server.name
        port = server.properties.port.value

        logger.info(
            'Server "%s" starting — provider=%s port=%d server_id=%s',
            server_name, provider_type, port, sid,
        )

        logger.info(
            'Claiming localhost ownership for server "%s" — server_id=%s',
            server_name, sid,
        )
        try:
            async with database.session_factory() as claim_session:
                claim_repo = SQLServerRepository(claim_session)
                claim_mgr = RuntimeOwnershipManager(claim_repo)
                claim_result = await claim_mgr.claim_localhost(sid)
            if claim_result.actions:
                logger.info(
                    'Localhost claim for "%s" completed %d actions — server_id=%s',
                    server_name, len(claim_result.actions), sid,
                )
                for action in claim_result.actions:
                    logger.debug("Claim action: %s", action)
            if claim_result.warnings:
                logger.warning(
                    'Localhost claim for "%s" had %d warnings — server_id=%s',
                    server_name, len(claim_result.warnings), sid,
                )
                for w in claim_result.warnings:
                    logger.warning("Claim warning: %s", w)
        except Exception as exc:
            logger.warning(
                'Localhost claim for "%s" failed but proceeding — error=%s server_id=%s',
                server_name, exc, sid,
            )

        logger.info(
            'Verifying port %d is free for server "%s" — server_id=%s',
            port, server_name, sid,
        )
        if _port_is_listening(port):
            occupant_pid = None
            try:
                from app.modules.server.application.runtime_ownership import _pid_for_port
                occupant_pid = _pid_for_port(port)
            except Exception:
                pass
            logger.error(
                'Port %d still occupied after ownership claim — server="%s" occupant_pid=%s server_id=%s',
                port, server_name, occupant_pid, sid,
            )
        else:
            logger.info(
                'Port %d is free for server "%s" — server_id=%s',
                port, server_name, sid,
            )

        with startup_timeline(server_name, sid):
            add_timeline_milestone(None, "Pre-flight started", server_name, sid)
            try:
                config = {
                    "java_args": server.java_args.as_list(),
                    "memory_min_mb": server.memory.min_mb,
                    "memory_max_mb": server.memory.max_mb,
                    "port": port,
                }
                add_timeline_milestone(None, "Calling provider.start()", server_name, sid)
                with progress_phase("Provider start", 1, 1, server_name, sid):
                    result = await asyncio.wait_for(
                        provider.start(
                            server_id=sid,
                            config=config,
                            deployment=server.deployment,
                            launch_config=server.launch_config,
                        ),
                        timeout=30,
                    )
                add_timeline_milestone(None, "Provider.start() completed", server_name, sid)
            except TimeoutError:
                logger.error(
                    'Server "%s" start timed out — provider=%s server_id=%s',
                    server_name, provider_type, sid,
                )
                async with UnitOfWork(self._event_bus) as uow:
                    repo = SQLServerRepository(uow.session)
                    server = await repo.get(server_id)
                    server.crash(exit_code=-1, last_log_lines=["Provider start timed out after 30s"])
                    await repo.save(server)
                    for event in server.collect_events():
                        uow.add_event(event)
                    await uow.commit()
                return CommandResult(
                    success=False,
                    error="Provider start timed out after 30s",
                    error_code="STARTUP_TIMEOUT",
                )
            except Exception as exc:
                logger.exception(
                    'Server "%s" start failed — provider=%s server_id=%s',
                    server_name, provider_type, sid,
                )
                async with UnitOfWork(self._event_bus) as uow:
                    repo = SQLServerRepository(uow.session)
                    server = await repo.get(server_id)
                    server.crash(exit_code=-1, last_log_lines=[str(exc)])
                    await repo.save(server)
                    for event in server.collect_events():
                        uow.add_event(event)
                    await uow.commit()
                return CommandResult(
                    success=False,
                    error=f"Provider failed to start server: {exc}",
                    error_code="PROVIDER_START_FAILED",
                )

            external_id = result.metadata.get("session_name", "")
            async with UnitOfWork(self._event_bus) as uow:
                repo = SQLServerRepository(uow.session)
                server = await repo.get(server_id)
                server.mark_running(
                    pid=result.pid or 0,
                    port=result.port,
                    host=result.address,
                    external_id=external_id,
                )
                await repo.save(server)
                for event in server.collect_events():
                    uow.add_event(event)
                    logger.info("EVENT %s", format_event(event, server_name))
                await uow.commit()

            logger.info(
                'Server "%s" started — pid=%s port=%s server_id=%s',
                server_name, result.pid, result.port, sid,
            )

            add_timeline_milestone(None, "Server marked running", server_name, sid)

            handle = ServerHandle(
                provider=provider_type,
                server_id=sid,
                external_id=external_id,
                metadata={
                    "pid": result.pid,
                    "port": result.port,
                    "server_name": server_name,
                },
            )

            RuntimeSupervisor.start_for(
                server=server,
                provider=provider,
                handle=handle,
                repo_get=lambda sid: sql_get_server(sid),
                repo_save=lambda s: sql_save_server(s, self._event_bus),
            )

            add_timeline_milestone(None, "Supervisor started", server_name, sid)

        return CommandResult(
            success=True,
            data={
                "server_id": command.server_id,
                "pid": result.pid,
                "port": result.port,
                "address": result.address,
            },
        )


async def sql_get_server(sid: ServerId) -> Server:
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.storage.db import database

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        return await repo.get(sid)


async def sql_save_server(server: Server, event_bus: EventBus) -> None:
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.storage.unit_of_work import UnitOfWork

    async with UnitOfWork(event_bus) as uow:
        repo = SQLServerRepository(uow.session)
        await repo.save(server)
        for event in server.collect_events():
            uow.add_event(event)
        await uow.commit()
