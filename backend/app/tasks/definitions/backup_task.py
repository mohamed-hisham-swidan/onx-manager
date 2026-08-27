from __future__ import annotations

import logging
from typing import Any

from app.api.deps import build_backup_encryption, build_storage_backend
from app.core.config import ConfigFactory
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.saga import SagaOrchestrator
from app.modules.backup.domain.aggregate import BackupType
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.services.backup_orchestrator import (
    BackupCancelledError,
    BackupSaga,
    clear_cancelled_backup,
    is_backup_cancelled,
)

logger = logging.getLogger(__name__)


async def run_backup_task(params: dict[str, Any]) -> dict[str, Any]:
    backup_id = BackupJobId(params["backup_id"])
    server_id = ServerId(params["server_id"])
    backup_type = BackupType(params.get("backup_type", "full"))

    settings = ConfigFactory.global_settings()
    storage = build_storage_backend(settings)
    encryption = build_backup_encryption(settings.backup_encryption_key_path)
    saga = BackupSaga(SagaOrchestrator())

    try:
        await saga.execute(
            backup_id=backup_id,
            server_id=server_id,
            storage=storage,
            encryption=encryption,
            backup_type=backup_type,
        )
    except BackupCancelledError as exc:
        logger.warning("Backup task cancelled: %s for server %s (%s)", backup_id, server_id, exc)
        async with UnitOfWork() as uow:
            repo = SQLBackupRepository(uow.session)
            job = await repo.get_job(backup_id)
            job.mark_failed_timeout(str(exc))
            await repo.save_job(job)
            await uow.commit()
        clear_cancelled_backup(str(backup_id))
        return {
            "backup_id": str(backup_id),
            "server_id": str(server_id),
            "status": "failed_timeout",
        }
    except Exception:
        logger.exception("Backup task failed: %s for server %s", backup_id, server_id)
        async with UnitOfWork() as uow:
            repo = SQLBackupRepository(uow.session)
            job = await repo.get_job(backup_id)
            if is_backup_cancelled(str(backup_id)):
                job.mark_failed_timeout("Backup cancelled due to timeout")
            else:
                job.mark_failed("Backup task failed")
            await repo.save_job(job)
            await uow.commit()
        clear_cancelled_backup(str(backup_id))
        raise

    logger.info("Backup task completed: %s for server %s", backup_id, server_id)
    return {"backup_id": str(backup_id), "server_id": str(server_id)}
