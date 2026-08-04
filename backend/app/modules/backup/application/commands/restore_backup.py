from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import NotFoundError, ServerNotFoundError
from app.core.idempotency import IdempotencyKey
from app.core.persistence.db import database
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.backup.application.restore_service import RestoreError, perform_safe_restore
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import BackupJobId

logger = logging.getLogger(__name__)

# Statuses in which the server process may still be up — restoring underneath a
# live process would corrupt the world, so these are deferred instead.
_NON_IDLE_STATUSES: frozenset[str] = frozenset({"running", "starting", "stopping", "crashed"})


class RestoreBackupCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    backup_id: str


class RestoreBackupHandler(CommandHandler[RestoreBackupCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

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

            if server.status.value in _NON_IDLE_STATUSES:
                requested_at = datetime.now(UTC)
                await backup_repo.upsert_pending_restore(job.server_id, backup_id, requested_at)
                await session.commit()
                logger.info(
                    "Restore deferred until next start — server_id=%s backup_id=%s status=%s",
                    server_id, command.backup_id, server.status.value,
                )
                return CommandResult(
                    success=True,
                    data={
                        "server_id": server_id,
                        "backup_id": command.backup_id,
                        "deferred": True,
                    },
                )

        try:
            restored_items = await perform_safe_restore(
                backup_id, server_dir, base_world=base_world,
            )
        except RestoreError as exc:
            logger.error(
                "Restore failed — server_id=%s backup_id=%s error=%s",
                server_id, command.backup_id, exc,
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

        logger.info(
            "Restore applied — server_id=%s backup_id=%s items=%s",
            server_id, command.backup_id, restored_items,
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
