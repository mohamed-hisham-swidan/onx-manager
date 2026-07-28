from __future__ import annotations

import logging
from typing import Any

from app.core.saga import SagaOrchestrator
from app.modules.backup.domain.aggregate import BackupJob, BackupType
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.modules.storage.base import StorageBackend
from app.services.backup_orchestrator import BackupSaga
from app.core.persistence.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


async def run_backup_task(params: dict[str, Any]) -> dict[str, Any]:
    server_id = ServerId(params["server_id"])
    saga_orchestrator: SagaOrchestrator = params["saga_orchestrator"]
    storage: StorageBackend = params["storage"]

    backup_id = BackupJobId()

    async with UnitOfWork() as uow:
        repo = SQLBackupRepository(uow.session)
        job = BackupJob.create(
            backup_id=backup_id,
            server_id=server_id,
            backup_type=BackupType(params.get("backup_type", "full")),
        )
        await repo.save_job(job)
        await uow.commit()

    saga = BackupSaga(saga_orchestrator)
    await saga.execute(
        backup_id=backup_id,
        server_id=server_id,
        storage=storage,
        encryption=params.get("encryption"),
    )

    logger.info("Backup task completed: %s for server %s", backup_id, server_id)
    return {"backup_id": str(backup_id), "server_id": str(server_id)}
