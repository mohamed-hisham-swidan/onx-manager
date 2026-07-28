from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId
from app.core.persistence.unit_of_work import UnitOfWork


class VerifyBackupCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    backup_id: str


class VerifyBackupHandler(CommandHandler[VerifyBackupCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: VerifyBackupCommand) -> CommandResult:
        backup_id = BackupJobId(command.backup_id)

        async with UnitOfWork(self._event_bus) as uow:
            repo: BackupRepository = SQLBackupRepository(uow.session)
            job = await repo.get_job(backup_id)
            checksum_valid = bool(job.checksum and len(job.checksum) > 0)
            size_valid = job.size_bytes > 0
            valid = checksum_valid and size_valid and job.status.value == "completed"

        return CommandResult(
            success=True,
            data={
                "backup_id": command.backup_id,
                "valid": valid,
                "checksum_valid": checksum_valid,
                "size_valid": size_valid,
            },
        )
