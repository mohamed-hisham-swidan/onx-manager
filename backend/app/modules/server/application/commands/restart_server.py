from __future__ import annotations

import asyncio
import logging
import time

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.exceptions import ServerNotRunningError
from app.core.persistence.db import database
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.backup.application.restore_service import RestoreError, consume_pending_restore
from app.modules.plugin.application.services.plugin_deletion_service import (
    consume_pending_plugin_deletions,
)
from app.modules.server.application.logging_utils import (
    add_timeline_milestone,
    format_event,
    progress_phase,
    shutdown_timeline,
    startup_timeline,
)
from app.modules.server.application.runtime_ownership import RuntimeOwnershipManager
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.backup.domain.aggregate import BackupStatus
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.server.domain.aggregate import ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.providers import provider_factory
from app.modules.server.infrastructure.providers.base import ServerHandle, ServerRuntimeStatus
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId

from app.core.identity import IDENTITY

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.commands.restart_server")

# TODO(STARTING-001-CFG): hardcoded for now; shares the future config system with the OQ-2 15-min supervisor startup timeout
_BACKUP_WAIT_CAP_S: float = 30.0


class RestartServerCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str


class RestartServerHandler(CommandHandler[RestartServerCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: RestartServerCommand) -> CommandResult:
        server_id = ServerId(command.server_id)
        sid = str(server_id)

        # Check for active backups for this server and wait up to _BACKUP_WAIT_CAP_S
        backup_deadline = time.monotonic() + _BACKUP_WAIT_CAP_S
        while True:
            async with database.session_factory() as bkp_session:
                bkp_repo = SQLBackupRepository(bkp_session)
                active_backups = [
                    b for b in await bkp_repo.list_jobs(server_id)
                    if b.status in (BackupStatus.PENDING, BackupStatus.IN_PROGRESS)
                ]
            if not active_backups:
                break
            if time.monotonic() >= backup_deadline:
                logger.warning(
                    'Restart backup-wait cap (%.1fs) exceeded for server "%s" — cancelling in-flight backup(s) and proceeding server_id=%s',
                    _BACKUP_WAIT_CAP_S, sid, sid,
                )
                from app.services.backup_orchestrator import cancel_backup
                for bkp in active_backups:
                    cancel_backup(str(bkp.backup_id))
                break
            await asyncio.sleep(0.5)

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerRepository = SQLServerRepository(uow.session)
            server = await repo.get(server_id)
            server_name = server.name
            if server.status not in (ServerStatus.RUNNING, ServerStatus.STARTING):
                raise ServerNotRunningError(sid)
            server.stop(reason="restart")
            server.mark_stopped()
            await repo.save(server)
            for event in server.collect_events():
                uow.add_event(event)
                logger.info("EVENT %s", format_event(event, server_name))
            await uow.commit()

        logger.info(
            'Server "%s" restarting — server_id=%s',
            server_name, sid,
        )

        stop_errors: list[str] = []

        with shutdown_timeline(server_name, sid):
            add_timeline_milestone(None, "Phase 1/2: Stop started", server_name, sid)
            await RuntimeSupervisor.stop_for(sid)

            if server.runtime and server.runtime.external_id:
                provider = provider_factory.get(server.runtime.provider)
                handle = ServerHandle(
                    provider=server.runtime.provider,
                    server_id=sid,
                    external_id=server.runtime.external_id,
                    metadata={"server_name": server_name},
                )

                try:
                    with progress_phase("Restart — stop", 1, 2, server_name, sid):
                        await asyncio.wait_for(provider.stop(handle), timeout=15)
                        status = await asyncio.wait_for(provider.status(handle), timeout=5)
                        if status != ServerRuntimeStatus.STOPPED:
                            stop_errors.append(f"Runtime still {status.value} after stop")
                except TimeoutError:
                    stop_errors.append("Stop timed out")
                    try:
                        await asyncio.wait_for(provider.stop(handle, force=True), timeout=10)
                    except Exception as exc:
                        stop_errors.append(f"Force stop failed: {exc}")
                except Exception as exc:
                    stop_errors.append(f"Stop failed: {exc}")
                    try:
                        await asyncio.wait_for(provider.stop(handle, force=True), timeout=10)
                    except Exception:
                        pass

                try:
                    server_port = server.properties.port.value if hasattr(server.properties, "port") else 25565
                    from app.modules.server.application.runtime_ownership import (
                        _port_is_listening,
                        _wait_for_port_free,
                    )
                    if _port_is_listening(server_port):
                        released = _wait_for_port_free(server_port, timeout=5.0)
                        if released:
                            logger.info(
                                'Port %d released during restart — server="%s" server_id=%s',
                                server_port, server_name, sid,
                            )
                        else:
                            stop_errors.append(f"Port {server_port} still listening after stop")
                    else:
                        logger.info(
                            'Port %d already free — server="%s" server_id=%s',
                            server_port, server_name, sid,
                        )
                except Exception as port_exc:
                    stop_errors.append(f"Port verification failed: {port_exc}")

            add_timeline_milestone(None, "Phase 1/2: Stop complete", server_name, sid)

        if stop_errors:
            logger.warning(
                'Server "%s" restart stop phase had %d issues — server_id=%s',
                server_name, len(stop_errors), sid,
            )

        # A restore deferred while the server was running must be applied now
        # that the process is confirmed down, before the new process spawns.
        if server.deployment is not None and server.deployment.root_path:
            try:
                restored_backup_id = await consume_pending_restore(
                    sid,
                    server.deployment.server_directory(),
                    base_world=server.deployment.primary_world or "world",
                )
            except RestoreError as exc:
                logger.error(
                    'Pending restore failed during restart — server="%s" server_id=%s error=%s',
                    server_name, sid, exc,
                )
                return CommandResult(
                    success=False,
                    error=f"Pending restore failed: {exc}",
                    error_code="RESTORE_FAILED",
                )
            if restored_backup_id:
                logger.info(
                    'Pending restore %s applied before restart — server="%s" server_id=%s',
                    restored_backup_id, server_name, sid,
                )

            # Deferred plugin deletions are applied the same way: the process is
            # confirmed down, so a running JVM can no longer hold the .jar open.
            # Unlike restore, a failure here must never block startup — log and
            # continue; the pending row is preserved for the next restart.
            try:
                await consume_pending_plugin_deletions(
                    sid,
                    server.deployment.server_directory(),
                )
            except Exception as exc:
                logger.warning(
                    'Pending plugin deletions failed during restart — server="%s" '
                    'server_id=%s error=%s',
                    server_name, sid, exc,
                )

        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLServerRepository(uow.session)
            server = await repo.get(server_id)

            if server.deployment is None:
                return CommandResult(
                    success=False,
                    error="Server has no deployment.",
                    error_code="NO_DEPLOYMENT",
                )

            provider_type = server.runtime.provider if server.runtime else "local"
            provider = provider_factory.get(provider_type)
            server.start()
            await repo.save(server)
            for event in server.collect_events():
                uow.add_event(event)
                logger.info("EVENT %s", format_event(event, server_name))
            await uow.commit()

        logger.info(
            'Claiming localhost ownership during restart — server="%s" server_id=%s',
            server_name, sid,
        )
        try:
            async with database.session_factory() as claim_session:
                claim_repo = SQLServerRepository(claim_session)
                claim_mgr = RuntimeOwnershipManager(claim_repo)
                claim_result = await claim_mgr.claim_localhost(sid)
            if claim_result.actions:
                logger.info(
                    'Localhost claim during restart for "%s" completed %d actions — server_id=%s',
                    server_name, len(claim_result.actions), sid,
                )
        except Exception as exc:
            logger.warning(
                'Localhost claim during restart for "%s" failed — error=%s server_id=%s',
                server_name, exc, sid,
            )

        with startup_timeline(server_name, sid):
            add_timeline_milestone(None, "Phase 2/2: Start initiated", server_name, sid)
            try:
                with progress_phase("Restart — start", 2, 2, server_name, sid):
                    result = await asyncio.wait_for(
                        provider.start(
                            server_id=sid,
                            deployment=server.deployment,
                            launch_config=server.launch_config,
                        ),
                        timeout=30,
                    )
            except TimeoutError:
                logger.error(
                    'Server "%s" restart start timed out — server_id=%s',
                    server_name, sid,
                )
                async with UnitOfWork(self._event_bus) as uow:
                    repo = SQLServerRepository(uow.session)
                    server = await repo.get(server_id)
                    server.crash(exit_code=-1, last_log_lines=["Provider start timed out during restart"])
                    await repo.save(server)
                    for event in server.collect_events():
                        uow.add_event(event)
                    await uow.commit()
                return CommandResult(
                    success=False,
                    error="Provider start timed out during restart",
                    error_code="STARTUP_TIMEOUT",
                    data={"stop_phase_errors": stop_errors} if stop_errors else None,
                )
            except Exception as exc:
                logger.exception(
                    'Server "%s" restart start failed — provider=%s server_id=%s',
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
                    error=f"Provider failed to start server during restart: {exc}",
                    error_code="PROVIDER_START_FAILED",
                    data={"stop_phase_errors": stop_errors} if stop_errors else None,
                )

            external_id = result.metadata.get("session_name", "")
            async with UnitOfWork(self._event_bus) as uow:
                repo = SQLServerRepository(uow.session)
                server = await repo.get(server_id)
                server.record_runtime_starting(
                    pid=result.pid or 0,
                    port=result.port,
                    host=result.address,
                    external_id=external_id,
                    start_time=result.metadata.get("start_time"),
                )
                await repo.save(server)
                for event in server.collect_events():
                    uow.add_event(event)
                    logger.info("EVENT %s", format_event(event, server_name))
                await uow.commit()

            logger.info(
                'Server "%s" restarted process spawned — pid=%s port=%s server_id=%s',
                server_name, result.pid, result.port, sid,
            )

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

            add_timeline_milestone(None, "Phase 2/2: Supervisor started", server_name, sid)

        result_data: dict = {
            "server_id": command.server_id,
            "pid": result.pid,
            "port": result.port,
            "address": result.address,
        }
        if stop_errors:
            result_data["stop_phase_warnings"] = stop_errors

        return CommandResult(success=True, data=result_data)


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
