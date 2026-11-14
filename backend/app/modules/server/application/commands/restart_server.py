from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ServerNotRunningError
from app.core.idempotency import IdempotencyKey
from app.core.identity import IDENTITY
from app.core.persistence.db import database
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.settings_store import get_live_settings
from app.modules.backup.application.restore_service import RestoreError, consume_pending_restore
from app.modules.backup.domain.aggregate import BackupStatus
from app.modules.backup.infrastructure.repository import SQLBackupRepository
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
from app.modules.server.application.runtime_ownership import (
    RuntimeOwnershipManager,
    _port_is_listening,
    _wait_for_port_free,
)
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
from app.modules.versioning.infrastructure.refresh_journal import (
    assert_no_unresolved_refresh,
)

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.commands.restart_server")

# TODO(STARTING-001-CFG): hardcoded for now; shares the future config system with the OQ-2 15-min supervisor startup timeout
_BACKUP_WAIT_CAP_S: float = 30.0
_GRACEFUL_STOP_TIMEOUT: float = 50.0
_FORCE_STOP_TIMEOUT: float = 15.0


class RestartServerCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    # Only the active refresh/rollback may exempt its own journal from the boot
    # guard; every other unresolved journal still blocks with HTTP 409.
    allow_journal_id: str | None = None


class RestartServerHandler(CommandHandler[RestartServerCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: RestartServerCommand) -> CommandResult:
        server_id = ServerId(command.server_id)
        sid = str(server_id)

        # Never stop or replace a tree while a refresh/rollback is unresolved.
        await assert_no_unresolved_refresh(
            sid, allow_journal_id=command.allow_journal_id
        )

        # Check for active backups for this server and wait up to _BACKUP_WAIT_CAP_S
        backup_deadline = time.monotonic() + _BACKUP_WAIT_CAP_S
        while True:
            async with database.session_factory() as bkp_session:
                bkp_repo = SQLBackupRepository(bkp_session)
                active_backups = [
                    b
                    for b in await bkp_repo.list_jobs(server_id)
                    if b.status in (BackupStatus.PENDING, BackupStatus.IN_PROGRESS)
                ]
            if not active_backups:
                break
            if time.monotonic() >= backup_deadline:
                logger.warning(
                    'Restart backup-wait cap (%.1fs) exceeded for server "%s" — cancelling in-flight backup(s) and proceeding server_id=%s',
                    _BACKUP_WAIT_CAP_S,
                    sid,
                    sid,
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
            if server.status not in (
                ServerStatus.RUNNING,
                ServerStatus.STARTING,
                ServerStatus.STOPPING,
            ):
                raise ServerNotRunningError(sid)

            if server.status in (ServerStatus.RUNNING, ServerStatus.STARTING):
                server.stop(reason="restart")
                await repo.save(server)
                for event in server.collect_events():
                    uow.add_event(event)
                    logger.info("EVENT %s", format_event(event, server_name))
                await uow.commit()

        logger.info(
            'Server "%s" restarting — server_id=%s',
            server_name,
            sid,
        )

        stop_errors: list[str] = []
        status: ServerRuntimeStatus | None = None
        server_dir = server.deployment.server_directory() if server.deployment else None
        provider_type = (
            server.runtime.provider
            if (server.runtime and server.runtime.provider)
            else default_provider_for_platform()
        )
        provider = provider_factory.get(provider_type)
        handle = build_server_handle(server, provider_type, server_dir=server_dir)

        has_runtime_handle = bool(
            server.runtime
            and server.runtime.external_id
            and (provider_type != "local_windows" or server.runtime.pid is not None)
        )

        with shutdown_timeline(server_name, sid):
            add_timeline_milestone(None, "Phase 1/2: Stop started", server_name, sid)
            await RuntimeSupervisor.stop_for(sid)

            if not has_runtime_handle:
                stop_errors.append("Cannot verify stop: server has no runtime handle")
            else:
                try:
                    with progress_phase("Restart — stop", 1, 2, server_name, sid):
                        await asyncio.wait_for(
                            provider.stop(handle), timeout=_GRACEFUL_STOP_TIMEOUT
                        )
                except TimeoutError:
                    stop_errors.append(f"Stop timed out after {_GRACEFUL_STOP_TIMEOUT:.0f}s")
                    try:
                        await asyncio.wait_for(
                            provider.stop(handle, force=True), timeout=_FORCE_STOP_TIMEOUT
                        )
                    except Exception as exc:
                        stop_errors.append(f"Force stop failed: {exc}")
                except Exception as exc:
                    stop_errors.append(f"Stop failed: {exc}")
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(
                            provider.stop(handle, force=True), timeout=_FORCE_STOP_TIMEOUT
                        )

                try:
                    status = await asyncio.wait_for(provider.status(handle), timeout=5)
                    if status != ServerRuntimeStatus.STOPPED:
                        stop_errors.append(f"Runtime still {status.value} after stop")
                except Exception as exc:
                    stop_errors.append(f"Provider status check failed after stop: {exc}")

            server_port = (
                server.properties.port.value
                if hasattr(server.properties, "port")
                and hasattr(server.properties.port, "value")
                else (server.runtime.port if server.runtime and server.runtime.port else 0)
            )

            port_free = True
            if server_port > 0:
                if _port_is_listening(server_port):
                    released = _wait_for_port_free(server_port, timeout=5.0)
                    if released:
                        logger.info(
                            'Port %d released during restart — server="%s" server_id=%s',
                            server_port,
                            server_name,
                            sid,
                        )
                    else:
                        port_free = False
                        stop_errors.append(f"Port {server_port} still listening after stop")
                else:
                    logger.info(
                        'Port %d already free — server="%s" server_id=%s',
                        server_port,
                        server_name,
                        sid,
                    )

            add_timeline_milestone(None, "Phase 1/2: Stop complete", server_name, sid)

        stop_confirmed = (
            has_runtime_handle
            and len(stop_errors) == 0
            and status == ServerRuntimeStatus.STOPPED
            and port_free
        )

        if not stop_confirmed:
            async with UnitOfWork(self._event_bus) as uow:
                repo = SQLServerRepository(uow.session)
                server = await repo.get(server_id)
                if status == ServerRuntimeStatus.RUNNING or not port_free:
                    if server.status == ServerStatus.STOPPING:
                        server.revert_to_running()
                        await repo.save(server)
                        for event in server.collect_events():
                            uow.add_event(event)
                        await uow.commit()
                else:
                    if server.status == ServerStatus.STOPPING:
                        server.mark_stop_unknown(reason="; ".join(stop_errors))
                        await repo.save(server)
                        for event in server.collect_events():
                            uow.add_event(event)
                        await uow.commit()

            logger.error(
                'Server "%s" restart failed during stop phase — server_id=%s errors=%s',
                server_name,
                sid,
                "; ".join(stop_errors),
            )
            return CommandResult(
                success=False,
                error="; ".join(stop_errors) or "Stop phase unconfirmed during restart",
                error_code="RESTART_STOP_FAILED",
                data={"stop_errors": stop_errors},
            )

        # Once stop is confirmed, mark stopped in DB and clean up container if docker
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLServerRepository(uow.session)
            server = await repo.get(server_id)
            server.mark_stopped()
            await repo.save(server)
            for event in server.collect_events():
                uow.add_event(event)
            await uow.commit()

        if provider_type == "docker":
            try:
                await provider.destroy(handle)
            except Exception as exc:
                logger.warning("Error destroying stopped container for restart %s: %s", sid, exc)

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
                    server_name,
                    sid,
                    exc,
                )
                return CommandResult(
                    success=False,
                    error=f"Pending restore failed: {exc}",
                    error_code="RESTORE_FAILED",
                )
            if restored_backup_id:
                logger.info(
                    'Pending restore %s applied before restart — server="%s" server_id=%s',
                    restored_backup_id,
                    server_name,
                    sid,
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
                    "server_id=%s error=%s",
                    server_name,
                    sid,
                    exc,
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

            server.start()
            await repo.save(server)
            for event in server.collect_events():
                uow.add_event(event)
                logger.info("EVENT %s", format_event(event, server_name))
            await uow.commit()

        logger.info(
            'Claiming localhost ownership during restart — server="%s" server_id=%s',
            server_name,
            sid,
        )
        try:
            async with database.session_factory() as claim_session:
                claim_repo = SQLServerRepository(claim_session)
                claim_mgr = RuntimeOwnershipManager(claim_repo)
                claim_result = await claim_mgr.claim_localhost(sid)
            if claim_result.actions:
                logger.info(
                    'Localhost claim during restart for "%s" completed %d actions — server_id=%s',
                    server_name,
                    len(claim_result.actions),
                    sid,
                )
        except Exception as exc:
            logger.warning(
                'Localhost claim during restart for "%s" failed — error=%s server_id=%s',
                server_name,
                exc,
                sid,
            )

        with startup_timeline(server_name, sid):
            add_timeline_milestone(None, "Phase 2/2: Start initiated", server_name, sid)
            try:
                config = {
                    "java_args": server.java_args.as_list(),
                    "memory_min_mb": server.memory.min_mb,
                    "memory_max_mb": server.memory.max_mb,
                    "port": server.properties.port.value,
                    "cpu_cores": server.cpu.cores,
                    "cpu_affinity": server.cpu.affinity,
                    "minecraft_version": str(server.minecraft_version),
                }
                await provider.prepare_environment(
                    server_id=sid,
                    config=config,
                    deployment=server.deployment,
                    launch_config=server.launch_config,
                )
                with progress_phase("Restart — start", 2, 2, server_name, sid):
                    result = await asyncio.wait_for(
                        provider.start(
                            server_id=sid,
                            config=config,
                            deployment=server.deployment,
                            launch_config=server.launch_config,
                        ),
                        timeout=30,
                    )
            except TimeoutError:
                logger.error(
                    'Server "%s" restart start timed out — server_id=%s',
                    server_name,
                    sid,
                )
                cleanup_handle = build_server_handle(
                    server,
                    provider_type,
                    server_dir=server.deployment.server_directory() if server.deployment else None,
                )
                try:
                    await provider.stop(cleanup_handle, force=True)
                except Exception as exc:
                    logger.warning("Error stopping timed-out server %s: %s", sid, exc)
                try:
                    await provider.destroy(cleanup_handle)
                except Exception as exc:
                    logger.warning("Error destroying timed-out server %s: %s", sid, exc)

                still_running = False
                try:
                    st = await provider.status(cleanup_handle)
                    if st == ServerRuntimeStatus.RUNNING:
                        still_running = True
                except Exception:
                    pass
                if server_port > 0 and _port_is_listening(server_port):
                    still_running = True

                async with UnitOfWork(self._event_bus) as uow:
                    repo = SQLServerRepository(uow.session)
                    server = await repo.get(server_id)
                    if still_running:
                        server.crash(reason="Restart start timed out and runtime cleanup failed")
                    else:
                        server.mark_stopped()
                    await repo.save(server)
                    for event in server.collect_events():
                        uow.add_event(event)
                    await uow.commit()
                return CommandResult(
                    success=False,
                    error="Provider start timed out during restart",
                    error_code="STARTUP_TIMEOUT",
                    details={
                        "provider": provider_type,
                        "server_id": sid,
                        "timeout_seconds": 30,
                    },
                    data={"stop_phase_errors": stop_errors} if stop_errors else None,
                )
            except Exception as exc:
                logger.exception(
                    'Server "%s" restart start failed — provider=%s server_id=%s',
                    server_name,
                    provider_type,
                    sid,
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
                    details={
                        "provider": provider_type,
                        "server_id": sid,
                        "detail": str(exc),
                    },
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
                server_name,
                result.pid,
                result.port,
                sid,
            )

            handle = build_server_handle(
                server,
                provider_type,
                server_dir=server.deployment.server_directory() if server.deployment else None,
            )

            RuntimeSupervisor.start_for(
                server=server,
                provider=provider,
                handle=handle,
                repo_get=lambda sid: sql_get_server(sid),
                repo_save=lambda s: sql_save_server(s, self._event_bus),
                startup_timeout=float(
                    server.startup_timeout_seconds
                    or get_live_settings().server_startup_timeout_seconds
                ),
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
