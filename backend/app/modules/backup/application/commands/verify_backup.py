from app.api.deps import build_backup_encryption, build_storage_backend
from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.config import ConfigFactory
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId


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

        artifact_present = False
        artifact_matches = False
        artifact_error = ""
        if job.status.value == "completed":
            try:
                settings = ConfigFactory.global_settings()
                storage = build_storage_backend(settings)
                encryption = build_backup_encryption(settings.backup_encryption_key_path)
                if not job.storage_path:
                    artifact_error = "backup has no stored artifact path"
                else:
                    data = await storage.read(job.storage_path)
                    artifact_present = len(data) > 0
                    actual_checksum = encryption.checksum(data)
                    artifact_matches = (
                        len(data) == job.size_bytes and actual_checksum == job.checksum
                    )
                    if not artifact_matches:
                        artifact_error = (
                            f"artifact mismatch: expected size={job.size_bytes} "
                            f"checksum={job.checksum}, got size={len(data)} "
                            f"checksum={actual_checksum}"
                        )
            except Exception as exc:
                artifact_error = str(exc)

        valid = checksum_valid and size_valid and artifact_present and artifact_matches

        return CommandResult(
            success=True,
            data={
                "backup_id": command.backup_id,
                "valid": valid,
                "checksum_valid": checksum_valid,
                "size_valid": size_valid,
                "artifact_present": artifact_present,
                "artifact_matches": artifact_matches,
                "artifact_error": artifact_error,
            },
        )
