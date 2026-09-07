from pydantic import Field

from app.api.deps import build_storage_backend
from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.config import ConfigFactory
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId


class DeleteBackupCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    backup_id: str


class DeleteBackupHandler(CommandHandler[DeleteBackupCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: DeleteBackupCommand) -> CommandResult:
        backup_id = BackupJobId(command.backup_id)

        async with UnitOfWork(self._event_bus) as uow:
            repo: BackupRepository = SQLBackupRepository(uow.session)
            job = await repo.get_job(backup_id)
            storage_path = job.storage_path

        if storage_path:
            try:
                storage = build_storage_backend(ConfigFactory.global_settings())
                await storage.delete(storage_path)
            except Exception as exc:
                return CommandResult(
                    success=False,
                    error=(f"Failed to delete backup artifact at {storage_path}: {exc}"),
                )

        async with UnitOfWork(self._event_bus) as uow:
            repo: BackupRepository = SQLBackupRepository(uow.session)
            job = await repo.get_job(backup_id)
            job.mark_deleted()
            await repo.delete_job(backup_id)
            for event in job.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data={"backup_id": command.backup_id})
