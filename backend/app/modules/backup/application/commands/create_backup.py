from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.modules.backup.domain.aggregate import BackupJob, BackupType
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.core.persistence.unit_of_work import UnitOfWork
from app.tasks.queue import get_task_queue

import logging

logger = logging.getLogger(__name__)


class CreateBackupCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str
    backup_type: str = "full"


class CreateBackupHandler(CommandHandler[CreateBackupCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: CreateBackupCommand) -> CommandResult:
        server_id = ServerId(command.server_id)
        backup_type = BackupType(command.backup_type)
        backup_id = BackupJobId()

        async with UnitOfWork(self._event_bus) as uow:
            repo: BackupRepository = SQLBackupRepository(uow.session)
            job = BackupJob.create(
                backup_id=backup_id,
                server_id=server_id,
                backup_type=backup_type,
            )
            await repo.save_job(job)
            for event in job.collect_events():
                uow.add_event(event)
            await uow.commit()

        try:
            await get_task_queue().enqueue(
                "run_backup_task",
                {
                    "backup_id": str(backup_id),
                    "server_id": str(server_id),
                    "backup_type": backup_type.value,
                },
            )
        except Exception as e:
            logger.exception("Failed to enqueue backup task for backup %s", backup_id)
            async with UnitOfWork(self._event_bus) as uow:
                repo: BackupRepository = SQLBackupRepository(uow.session)
                job = await repo.get_job(backup_id)
                job.mark_failed(f"enqueue failed: {type(e).__name__}: {e}")
                await repo.save_job(job)
                for event in job.collect_events():
                    uow.add_event(event)
                await uow.commit()
            return CommandResult(
                success=False,
                error=f"Failed to enqueue backup task: {type(e).__name__}: {e}",
                error_code="BACKUP_ENQUEUE_FAILED",
            )

        return CommandResult(success=True, data={"backup_id": str(backup_id)})
