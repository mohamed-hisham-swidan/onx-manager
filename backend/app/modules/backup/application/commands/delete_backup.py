from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId
from app.core.persistence.unit_of_work import UnitOfWork


class DeleteBackupCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    backup_id: str


class DeleteBackupHandler(CommandHandler[DeleteBackupCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: DeleteBackupCommand) -> CommandResult:
        backup_id = BackupJobId(command.backup_id)

        async with UnitOfWork(self._event_bus) as uow:
            repo: BackupRepository = SQLBackupRepository(uow.session)
            job = await repo.get_job(backup_id)
            job.mark_deleted()
            await repo.delete_job(backup_id)
            for event in job.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data={"backup_id": command.backup_id})
