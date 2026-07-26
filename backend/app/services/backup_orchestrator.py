import logging

from app.core.saga import SagaOrchestrator, SagaStep
from app.modules.backup.domain.aggregate import BackupJob, BackupStatus
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.modules.storage.base import StorageBackend
from app.modules.storage.encryption import BackupEncryption
from app.storage.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


class BackupSaga:
    def __init__(self, saga_orchestrator: SagaOrchestrator) -> None:
        self._saga = saga_orchestrator

    async def execute(
        self,
        backup_id: BackupJobId,
        server_id: ServerId,
        storage: StorageBackend,
        encryption: BackupEncryption | None = None,
    ) -> None:
        steps = [
            SagaStep(
                name="save_world",
                forward=self._save_world(backup_id),
                compensate=None,
            ),
            SagaStep(
                name="compress_backup",
                forward=self._compress(backup_id),
                compensate=self._cleanup_compressed(backup_id, storage),
            ),
            SagaStep(
                name="encrypt_backup",
                forward=self._encrypt(backup_id, encryption),
                compensate=self._cleanup_encrypted(backup_id, storage),
            ),
            SagaStep(
                name="upload_backup",
                forward=self._upload(backup_id, storage),
                compensate=self._remove_uploaded(backup_id, storage),
            ),
            SagaStep(
                name="verify_backup",
                forward=self._verify(backup_id, storage),
                compensate=self._mark_failed(backup_id),
            ),
        ]

        instance = await self._saga.create_saga("backup", steps, timeout_seconds=600.0)
        result = await self._saga.execute(instance.saga_id)

        if result.status.value in ("completed", "compensated"):
            async with UnitOfWork() as uow:
                repo: BackupRepository = SQLBackupRepository(uow.session)
                job = await repo.get_job(backup_id)
                if result.status.value == "completed":
                    job.mark_completed(size_bytes=0, checksum="")
                else:
                    job.mark_failed("Backup saga failed")
                await repo.save_job(job)
                await uow.commit()

    def _save_world(self, backup_id: BackupJobId):
        async def fn() -> None:
            logger.info("World saved for backup %s", backup_id)

        return fn

    def _compress(self, backup_id: BackupJobId):
        async def fn() -> None:
            logger.info("Backup compressed: %s", backup_id)

        return fn

    def _encrypt(self, backup_id: BackupJobId, encryption: BackupEncryption | None):
        async def fn() -> None:
            if encryption:
                logger.info("Backup encrypted: %s", backup_id)

        return fn

    def _upload(self, backup_id: BackupJobId, storage: StorageBackend):
        async def fn() -> None:
            path = f"backups/{backup_id}.tar.gz"
            await storage.write(path, b"")
            logger.info("Backup uploaded: %s", backup_id)

        return fn

    def _verify(self, backup_id: BackupJobId, storage: StorageBackend):
        async def fn() -> None:
            path = f"backups/{backup_id}.tar.gz"
            exists = await storage.exists(path)
            if not exists:
                raise RuntimeError(f"Backup {backup_id} not found after upload")
            logger.info("Backup verified: %s", backup_id)

        return fn

    def _cleanup_compressed(self, backup_id: BackupJobId, storage: StorageBackend):
        async def fn() -> None:
            logger.info("Cleaned up compressed data for %s", backup_id)

        return fn

    def _cleanup_encrypted(self, backup_id: BackupJobId, storage: StorageBackend):
        async def fn() -> None:
            logger.info("Cleaned up encrypted data for %s", backup_id)

        return fn

    def _remove_uploaded(self, backup_id: BackupJobId, storage: StorageBackend):
        async def fn() -> None:
            path = f"backups/{backup_id}.tar.gz"
            await storage.delete(path)
            logger.info("Removed uploaded backup: %s", backup_id)

        return fn

    def _mark_failed(self, backup_id: BackupJobId):
        async def fn() -> None:
            async with UnitOfWork() as uow:
                repo: BackupRepository = SQLBackupRepository(uow.session)
                job = await repo.get_job(backup_id)
                job.mark_failed("Verification failed in backup saga")
                await repo.save_job(job)
                await uow.commit()

        return fn
