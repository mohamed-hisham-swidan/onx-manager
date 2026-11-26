from pathlib import Path

from pydantic import Field

from app.api.deps import build_backup_encryption, build_storage_backend
from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.config import ConfigFactory
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.backup.infrastructure.tier1_snapshot import (
    Tier1SnapshotError,
    _directory_checksum_and_size,
    validate_tier1_complete_marker,
)
from app.modules.shared.value_objects import BackupJobId


class VerifyBackupCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
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
        if job.status.value != "completed":
            artifact_error = f"Backup status is '{job.status.value}', not 'completed'"
        else:
            try:
                settings = ConfigFactory.global_settings()
                storage = build_storage_backend(settings)
                encryption = build_backup_encryption(settings.backup_encryption_key_path)
                if not job.storage_path:
                    artifact_error = "Backup has no stored artifact path"
                else:
                    snap_path = Path(job.storage_path)
                    if (
                        not snap_path.is_dir()
                        and not snap_path.is_absolute()
                        and hasattr(storage, "base_path")
                    ):
                        candidate = Path(storage.base_path) / job.storage_path
                        if candidate.is_dir():
                            snap_path = candidate

                    if snap_path.is_dir():
                        artifact_present = True
                        try:
                            validate_tier1_complete_marker(snap_path)
                            actual_size, actual_checksum = _directory_checksum_and_size(snap_path)
                            artifact_matches = (
                                actual_size == job.size_bytes
                                and actual_checksum == job.checksum
                            )
                            if not artifact_matches:
                                artifact_error = (
                                    f"Snapshot mismatch: expected size={job.size_bytes} "
                                    f"checksum={job.checksum}, got size={actual_size} "
                                    f"checksum={actual_checksum}"
                                )
                        except Tier1SnapshotError as exc:
                            artifact_matches = False
                            artifact_error = str(exc)
                    else:
                        data = await storage.read(job.storage_path)
                        artifact_present = len(data) > 0
                        if not artifact_present:
                            artifact_error = (
                                f"Backup artifact is empty or missing at {job.storage_path}"
                            )
                        else:
                            actual_checksum = encryption.checksum(data)
                            artifact_matches = (
                                len(data) == job.size_bytes
                                and actual_checksum == job.checksum
                            )
                            if not artifact_matches:
                                artifact_error = (
                                    f"Artifact mismatch: expected size={job.size_bytes} "
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
                "artifact_error": artifact_error or None,
            },
        )
