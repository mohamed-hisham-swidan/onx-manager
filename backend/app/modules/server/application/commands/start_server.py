from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.identity import IDENTITY
from app.core.persistence.db import database
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.settings_store import get_live_settings
from app.modules.backup.application.restore_service import RestoreError, consume_pending_restore
from app.modules.plugin.application.services.plugin_deletion_service import (
    consume_pending_plugin_deletions,
)
from app.modules.server.application.logging_utils import (
    add_timeline_milestone,
    format_event,
    progress_phase,
    startup_timeline,
)
from app.modules.server.application.runtime_ownership import (
    RuntimeOwnershipManager,
    _port_is_listening,
)
from app.modules.server.application.startup_guard import check_startup_readiness
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import (
    build_server_handle,
    default_provider_for_platform,
)
from app.modules.server.infrastructure.providers import provider_factory
from app.modules.server.infrastructure.providers.base import (
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.modules.versioning.infrastructure.refresh_journal import (
    assert_no_unresolved_refresh,
)

if TYPE_CHECKING:
    from app.modules.server.application.lifecycle_lock import ServerLifecycleLeaseManager

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.commands.start_server")


class StartServerCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    # Only the active refresh/rollback may exempt its own journal from the boot
    # guard; every other unresolved journal still blocks with HTTP 409.
    allow_journal_id: str | None = None


class StartServerHandler(CommandHandler[StartServerCommand]):
    def __init__(
        self,
        event_bus: EventBus,
        provider: ServerProvider | None = None,
        lifecycle_lease: ServerLifecycleLeaseManager | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._provider = provider
        self._lifecycle_lease = lifecycle_lease

    async def handle(self, command: StartServerCommand) -> CommandResult:
        # Fail closed before stopping, claiming, or spawning anything when a
        # refresh/rollback journal is still unresolved.
        await assert_no_unresolved_refresh(
            command.server_id, allow_journal_id=command.allow_journal_id
        )
        if self._lifecycle_lease is not None:
            async with self._lifecycle_lease.acquire(
                command.server_id,
                holder=f"StartServerCommand:{os.getpid()}",
                wait_timeout=60.0,
            ):
                return await self._handle_locked(command)
        return await self._handle_locked(command)

    async def _handle_locked(self, command: StartServerCommand) -> CommandResult:
        server_id = ServerId(command.server_id)
        sid = str(server_id)

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerRepository = SQLServerRepository(uow.session)
            server = await repo.get(server_id)

            server_dir = (
                server.deployment.server_directory()
                if server.deployment
                else None
            )

            provider_type = (
                server.runtime.provider
                if (server.runtime and server.runtime.provider)
                else default_provider_for_platform()
            )
            provider = (
                self._provider
                if self._provider is not None
                else provider_factory.get(provider_type)
            )
            provider_name = getattr(provider, "name", provider_type)

            # Idempotent status re-check inside the lock
            if server.status == ServerStatus.RUNNING:
                handle = build_server_handle(server, provider_name, server_dir)
                runtime_status = await provider.status(handle)
                if runtime_status == ServerRuntimeStatus.RUNNING:
                    active_supervisor = RuntimeSupervisor.get_for(sid)
                    if not active_supervisor or not active_supervisor.is_running:
                        RuntimeSupervisor.start_for(
                            server=server,
                            provider=provider,
                            handle=handle,
                            repo_get=lambda s_id: sql_get_server(s_id),
                            repo_save=lambda s: sql_save_server(s, self._event_bus),
                            startup_timeout=float(
                                server.startup_timeout_seconds
                                or get_live_settings().server_startup_timeout_seconds
                            ),
                        )
                    return CommandResult(
                        success=True,
                        data={"server_id": sid, "status": "running", "idempotent": True},
                    )
                else:
                    await RuntimeSupervisor.stop_for(sid)
                    server.mark_stopped()
                    await repo.save(server)
                    for event in server.collect_events():
                        uow.add_event(event)

            elif server.status == ServerStatus.STARTING:
                if server.runtime and server.runtime.external_id:
                    handle = build_server_handle(server, provider_name, server_dir)
                    runtime_status = await provider.status(handle)
                    if runtime_status == ServerRuntimeStatus.RUNNING:
                        return CommandResult(
                            success=True,
                            data={"server_id": sid, "status": "starting", "idempotent": True},
                        )
                handle = build_server_handle(server, provider_name, server_dir)
                try:
                    await provider.stop(handle, force=True)
                except Exception as exc:
                    logger.debug("Error stopping partial runtime for %s: %s", sid, exc)
                await RuntimeSupervisor.stop_for(sid)
                server.mark_stopped()
                await repo.save(server)
                for event in server.collect_events():
                    uow.add_event(event)

            elif server.status in (
                ServerStatus.PROVISIONING,
                ServerStatus.RESTORING,
                ServerStatus.STOPPING,
            ):
                return CommandResult(
                    success=False,
                    error=f"Cannot start server while in '{server.status.value}' state",
                    error_code="SERVER_BUSY",
                )

            elif server.status in (
                ServerStatus.PROVISIONING_FAILED,
                ServerStatus.BROKEN,
            ):
                return CommandResult(
                    success=False,
                    error=f"Cannot start server in '{server.status.value}' state",
                    error_code="INVALID_SERVER_STATE",
                )

            if server.deployment is None:
                return CommandResult(
                    success=False,
                    error=(
                        "Server has no deployment. Configure install_dir or set up "
                        "a deployment path."
                    ),
                    error_code="NO_DEPLOYMENT",
                )

            if server.runtime and server.runtime.external_id:
                logger.warning(
                    'Server "%s" has stale runtime handle "%s" — cleaning up '
                    "before start server_id=%s",
                    server.name,
                    server.runtime.external_id,
                    sid,
                )

            guard_result = await check_startup_readiness(
                sid,
                root_path=server.deployment.server_directory() if server.deployment else None,
            )
            if not guard_result.allowed:
                logger.warning(
                    'Startup guard blocked server="%s" — %s server_id=%s',
                    server.name,
                    "; ".join(guard_result.reasons),
                    sid,
                )
                return CommandResult(
                    success=False,
                    error=f"Startup guard blocked: {'; '.join(guard_result.reasons)}",
                    error_code="STARTUP_BLOCKED",
                )
            if guard_result.warnings:
                logger.warning(
                    'Startup guard warnings for "%s" — %s server_id=%s',
                    server.name,
                    "; ".join(guard_result.warnings),
                    sid,
                )

            await RuntimeSupervisor.stop_for(sid)
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
            server_name,
            provider_type,
            port,
            sid,
        )

        logger.info(
            'Claiming localhost ownership for server "%s" — server_id=%s',
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
                    'Localhost claim for "%s" completed %d actions — server_id=%s',
                    server_name,
                    len(claim_result.actions),
                    sid,
                )
                for action in claim_result.actions:
                    logger.debug("Claim action: %s", action)
            if claim_result.warnings:
                logger.warning(
                    'Localhost claim for "%s" had %d warnings — server_id=%s',
                    server_name,
                    len(claim_result.warnings),
                    sid,
                )
                for w in claim_result.warnings:
                    logger.warning("Claim warning: %s", w)
        except Exception as exc:
            logger.warning(
                'Localhost claim for "%s" failed but proceeding — error=%s server_id=%s',
                server_name,
                exc,
                sid,
            )

        logger.info(
            'Verifying port %d is free for server "%s" — server_id=%s',
            port,
            server_name,
            sid,
        )
        if _port_is_listening(port):
            occupant_pid = None
            try:
                from app.modules.server.application.runtime_ownership import _pid_for_port

                occupant_pid = _pid_for_port(port)
            except Exception:
                pass
            logger.error(
                'Port %d still occupied after ownership claim — server="%s" '
                "occupant_pid=%s server_id=%s",
                port,
                server_name,
                occupant_pid,
                sid,
            )
            async with UnitOfWork(self._event_bus) as uow:
                repo = SQLServerRepository(uow.session)
                server = await repo.get(server_id)
                server.mark_stopped()
                await repo.save(server)
                for event in server.collect_events():
                    uow.add_event(event)
                await uow.commit()
            return CommandResult(
                success=False,
                error=f"Port {port} is still occupied; refusing to start server",
                error_code="PORT_OCCUPIED",
            )
        else:
            logger.info(
                'Port %d is free for server "%s" — server_id=%s',
                port,
                server_name,
                sid,
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
                    'Pending restore failed during start — server="%s" server_id=%s error=%s',
                    server_name,
                    sid,
                    exc,
                )
                async with UnitOfWork(self._event_bus) as uow:
                    repo = SQLServerRepository(uow.session)
                    server = await repo.get(server_id)
                    server.crash(exit_code=-1, last_log_lines=[f"Pending restore failed: {exc}"])
                    await repo.save(server)
                    for event in server.collect_events():
                        uow.add_event(event)
                    await uow.commit()
                return CommandResult(
                    success=False,
                    error=f"Pending restore failed: {exc}",
                    error_code="RESTORE_FAILED",
                )
            if restored_backup_id:
                logger.info(
                    'Pending restore %s applied before start — server="%s" server_id=%s',
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
                    'Pending plugin deletions failed during start — server="%s" '
                    "server_id=%s error=%s",
                    server_name,
                    sid,
                    exc,
                )

        with startup_timeline(server_name, sid):
            add_timeline_milestone(None, "Pre-flight started", server_name, sid)
            try:
                config = {
                    "java_args": server.java_args.as_list(),
                    "memory_min_mb": server.memory.min_mb,
                    "memory_max_mb": server.memory.max_mb,
                    "port": port,
                    "cpu_cores": server.cpu.cores,
                    "cpu_affinity": server.cpu.affinity,
                    "minecraft_version": str(server.minecraft_version),
                }
                add_timeline_milestone(None, "Preparing provider environment", server_name, sid)
                await provider.prepare_environment(
                    server_id=sid,
                    config=config,
                    deployment=server.deployment,
                    launch_config=server.launch_config,
                )
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
                    server_name,
                    provider_type,
                    sid,
                )
                cleanup_handle = ServerHandle(
                    provider=provider_type,
                    server_id=sid,
                    external_id=f"onx-{sid}",
                    metadata={"server_dir": str(server_dir), "port": port},
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
                if _port_is_listening(port):
                    still_running = True

                async with UnitOfWork(self._event_bus) as uow:
                    repo = SQLServerRepository(uow.session)
                    server = await repo.get(server_id)
                    if still_running:
                        server.crash(reason="Start timed out and runtime cleanup failed")
                    else:
                        server.mark_stopped()
                    await repo.save(server)
                    for event in server.collect_events():
                        uow.add_event(event)
                    await uow.commit()
                return CommandResult(
                    success=False,
                    error="Provider start timed out after 30s",
                    error_code="STARTUP_TIMEOUT",
                    details={
                        "provider": provider_type,
                        "server_id": sid,
                        "timeout_seconds": 30,
                    },
                )
            except Exception as exc:
                logger.exception(
                    'Server "%s" start failed — provider=%s server_id=%s',
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
                    error=f"Provider failed to start server: {exc}",
                    error_code="PROVIDER_START_FAILED",
                    details={
                        "provider": provider_type,
                        "server_id": sid,
                        "detail": str(exc),
                    },
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
                'Server "%s" starting process spawned — pid=%s port=%s server_id=%s',
                server_name,
                result.pid,
                result.port,
                sid,
            )

            add_timeline_milestone(None, "Process spawned, starting recorded", server_name, sid)

            handle = build_server_handle(server, provider_type, server_dir)

            RuntimeSupervisor.start_for(
                server=server,
                provider=provider,
                handle=handle,
                repo_get=lambda s_id: sql_get_server(s_id),
                repo_save=lambda s: sql_save_server(s, self._event_bus),
                startup_timeout=float(
                    server.startup_timeout_seconds
                    or get_live_settings().server_startup_timeout_seconds
                ),
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
