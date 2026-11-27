from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import NotFoundError, ServerNotFoundError
from app.core.idempotency import IdempotencyKey
from app.core.persistence.db import database
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.backup.application.restore_service import (
    RestoreError,
    dispatch_two_tier_restore,
)
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.server.application.lifecycle_lock import ServerLifecycleLockTimeoutError
from app.modules.server.application.runtime_ownership import _port_is_listening
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import BackupJobId

logger = logging.getLogger(__name__)


async def perform_safe_restore(
    job: object,
    server_dir: str,
    base_world: str = "world",
) -> list[str]:
    """Dispatch restore through the two-tier path for the restore command.

    Kept as a module-level seam so existing callers/tests can patch it without
    reaching into ``restore_service``.
    """
    return await dispatch_two_tier_restore(job, server_dir, base_world=base_world)

# Statuses in which the server process may still be up — restoring underneath a
# live process would corrupt the world, so these are deferred instead.
_NON_IDLE_STATUSES: frozenset[str] = frozenset(
    {"running", "starting", "stopping", "crashed", "restoring"}
)


class RestoreBackupCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    backup_id: str
    defer_if_running: bool = True


class RestoreBackupHandler(CommandHandler[RestoreBackupCommand]):
    def __init__(
        self,
        event_bus: EventBus,
        lifecycle_lease: Any | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._lifecycle_lease = lifecycle_lease

    async def handle(self, command: RestoreBackupCommand) -> CommandResult:
        backup_id = BackupJobId(command.backup_id)

        async with database.session_factory() as session:
            backup_repo: BackupRepository = SQLBackupRepository(session)
            try:
                job = await backup_repo.get_job(backup_id)
            except NotFoundError as exc:
                return CommandResult(success=False, error=str(exc), error_code="NOT_FOUND")

            if not job.storage_path:
                return CommandResult(
                    success=False,
                    error="Backup has no stored artifact; nothing to restore",
                    error_code="BACKUP_STORAGE_MISSING",
                )

        if self._lifecycle_lease is not None:
            try:
                async with self._lifecycle_lease.acquire(
                    str(job.server_id),
                    holder="RestoreBackupCommand",
                    wait_timeout=60.0,
                ):
                    return await self._execute(command, job, backup_id)
            except ServerLifecycleLockTimeoutError:
                return CommandResult(
                    success=False,
                    error="Another lifecycle operation is already in progress for this server",
                    error_code="OPERATION_CONCURRENCY_CONFLICT",
                )

        return await self._execute(command, job, backup_id)

    async def _execute(
        self, command: RestoreBackupCommand, job: Any, backup_id: BackupJobId
    ) -> CommandResult:
        async with database.session_factory() as session:
            backup_repo: BackupRepository = SQLBackupRepository(session)
            server_repo = SQLServerRepository(session)
            try:
                server = await server_repo.get(job.server_id)
            except ServerNotFoundError as exc:
                return CommandResult(success=False, error=str(exc), error_code="NOT_FOUND")

            server_id = str(server.id)
            if server.deployment is None or not server.deployment.root_path:
                return CommandResult(
                    success=False,
                    error="Server has no deployment; cannot resolve world directory",
                    error_code="NO_DEPLOYMENT",
                )
            server_dir = server.deployment.server_directory()
            base_world = server.deployment.primary_world or "world"

            status_val = (
                server.status.value.lower()
                if hasattr(server.status, "value")
                else str(server.status).lower()
            )

            has_active_runtime = False
            ext_id = getattr(server.runtime, "external_id", None) if server.runtime else None
            pid_val = getattr(server.runtime, "pid", None) if server.runtime else None
            if ext_id:
                try:
                    from app.modules.server.domain.value_objects import (
                        build_server_handle,
                        default_provider_for_platform,
                    )
                    from app.modules.server.infrastructure.providers import provider_factory
                    from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus

                    prov_name = (
                        getattr(server.runtime, "provider", None)
                        or default_provider_for_platform()
                    )
                    provider = provider_factory.get(prov_name)
                    handle = build_server_handle(server, prov_name, server_dir=server_dir)
                    live_rt_status = await provider.status(handle)
                    has_active_runtime = live_rt_status == ServerRuntimeStatus.RUNNING
                except Exception:
                    has_active_runtime = status_val in _NON_IDLE_STATUSES
            elif pid_val:
                try:
                    import psutil

                    has_active_runtime = psutil.pid_exists(int(pid_val))
                except Exception:
                    has_active_runtime = status_val in _NON_IDLE_STATUSES
            port_val = None
            if server.runtime and getattr(server.runtime, "port", None):
                port_val = server.runtime.port
            elif getattr(server, "properties", None) and getattr(server.properties, "port", None):
                p = server.properties.port
                port_val = p.value if hasattr(p, "value") else int(p)
            port_listening = _port_is_listening(port_val) if port_val else False

            is_active = (
                status_val in _NON_IDLE_STATUSES
                or has_active_runtime
                or port_listening
            )

            if is_active:
                if not getattr(command, "defer_if_running", True):
                    return CommandResult(
                        success=False,
                        error="Server runtime is still active; cannot perform live disk restore",
                        error_code="RESTORE_SERVER_ACTIVE",
                    )
                requested_at = datetime.now(UTC)
                await backup_repo.upsert_pending_restore(job.server_id, backup_id, requested_at)
                await session.commit()
                logger.info(
                    "Restore deferred until next start — server_id=%s backup_id=%s status=%s "
                    "(runtime_active=%s, port_listening=%s)",
                    server_id,
                    command.backup_id,
                    status_val,
                    has_active_runtime,
                    port_listening,
                )
                return CommandResult(
                    success=True,
                    data={
                        "server_id": server_id,
                        "backup_id": command.backup_id,
                        "deferred": True,
                    },
                )

        # ISS-022: Lock server into RESTORING state so concurrent starts are rejected
        async with UnitOfWork(self._event_bus) as uow:
            server_repo = SQLServerRepository(uow.session)
            try:
                server = await server_repo.get(job.server_id)
            except ServerNotFoundError as exc:
                return CommandResult(success=False, error=str(exc), error_code="NOT_FOUND")

            if server.deployment is None or not server.deployment.root_path:
                return CommandResult(
                    success=False,
                    error="Server has no deployment; cannot resolve world directory",
                    error_code="NO_DEPLOYMENT",
                )
            server_dir = server.deployment.server_directory()
            base_world = server.deployment.primary_world or "world"

            server.mark_restoring()
            await server_repo.save(server)
            await uow.commit()

        try:
            try:
                restored_items = await perform_safe_restore(
                    job,
                    server_dir,
                    base_world=base_world,
                )
            except RestoreError as exc:
                logger.error(
                    "Restore failed — server_id=%s backup_id=%s error=%s",
                    server_id,
                    command.backup_id,
                    exc,
                )
                return CommandResult(success=False, error=str(exc), error_code="RESTORE_FAILED")

            async with UnitOfWork(self._event_bus) as uow:
                repo: BackupRepository = SQLBackupRepository(uow.session)
                job = await repo.get_job(backup_id)
                job.mark_restored()
                await repo.save_job(job)
                for event in job.collect_events():
                    uow.add_event(event)
                await uow.commit()
        finally:
            async with UnitOfWork(self._event_bus) as uow:
                server_repo = SQLServerRepository(uow.session)
                try:
                    server = await server_repo.get(job.server_id)
                    server.mark_restore_completed()
                    await server_repo.save(server)
                    await uow.commit()
                except Exception as e:
                    logger.warning("Failed to reset server status after restore: %s", e)

        logger.info(
            "Restore applied — server_id=%s backup_id=%s items=%s",
            server_id,
            command.backup_id,
            restored_items,
        )
        return CommandResult(
            success=True,
            data={
                "server_id": server_id,
                "backup_id": command.backup_id,
                "deferred": False,
                "restored_items": restored_items,
            },
        )
