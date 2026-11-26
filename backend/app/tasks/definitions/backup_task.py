from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.api.deps import build_backup_encryption, build_storage_backend, get_optional_event_bus
from app.core.config import ConfigFactory
from app.core.exceptions import CasUnsupportedPlatformError
from app.core.host_state import ensure_host_state_layout
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.saga import SagaOrchestrator
from app.modules.backup.domain.aggregate import (
    BackupJob,
    BackupTier,
    BackupType,
    parse_backup_tier,
)
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.backup.infrastructure.tier1_snapshot import create_tier1_snapshot
from app.modules.backup.infrastructure.tier2_archive import create_tier2_archive
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.modules.versioning.application.baseline_adoption import (
    ensure_simple_baseline_lockfile,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.services.backup_orchestrator import (
    BackupCancelledError,
    BackupSaga,
    clear_cancelled_backup,
    is_backup_cancelled,
)

logger = logging.getLogger(__name__)


async def run_backup_task(params: dict[str, Any]) -> dict[str, Any]:
    server_id = ServerId(params["server_id"])
    backup_type = BackupType(params.get("backup_type", "full"))
    tier = parse_backup_tier(params.get("tier", "tier_1"))
    use_two_tier = bool(params.get("two_tier", False)) or tier == BackupTier.TIER_2
    event_bus = get_optional_event_bus()

    if "backup_id" not in params and params.get("scheduled"):
        backup_id = BackupJobId()
        async with UnitOfWork(event_bus=event_bus) as uow:
            repo = SQLBackupRepository(uow.session)
            if tier == BackupTier.TIER_2:
                job = BackupJob.create_tier2(
                    backup_id=backup_id,
                    server_id=server_id,
                    backup_type=backup_type,
                )
            else:
                job = BackupJob.create_tier1(
                    backup_id=backup_id,
                    server_id=server_id,
                    backup_type=backup_type,
                )
            await repo.save_job(job)
            for event in job.collect_events():
                uow.add_event(event)
            await uow.commit()
    else:
        backup_id = BackupJobId(params["backup_id"])

    settings = ConfigFactory.global_settings()
    storage = build_storage_backend(settings)
    encryption = build_backup_encryption(settings.backup_encryption_key_path)
    saga = BackupSaga(SagaOrchestrator(), event_bus=event_bus)

    try:
        try:
            adoption = await ensure_simple_baseline_lockfile(str(server_id))
            logger.info(
                "Baseline adoption status=%s reason=%s files_count=%d cas_ingested=%d "
                "for backup %s server %s",
                adoption.status,
                adoption.reason,
                adoption.files_count,
                adoption.cas_ingested,
                backup_id,
                server_id,
            )
            for quarantined_path in adoption.quarantined:
                logger.warning(
                    "Quarantined path during baseline adoption: %s for backup %s server %s",
                    quarantined_path,
                    backup_id,
                    server_id,
                )
        except CasUnsupportedPlatformError:
            logger.warning(
                "adoption_skipped_unsupported_platform for backup %s server %s",
                backup_id,
                server_id,
            )

        if use_two_tier:
            async with UnitOfWork() as uow:
                server_repo = SQLServerRepository(uow.session)
                server = await server_repo.get(server_id)
                if server.deployment is None or not server.deployment.root_path:
                    raise RuntimeError(f"Server {server_id} has no root_path")
                server_dir = Path(server.deployment.server_directory())
                is_running = server.status.value == "running"

            layout = ensure_host_state_layout(settings)
            if tier == BackupTier.TIER_1:
                snap = await create_tier1_snapshot(
                    server_id=str(server_id),
                    server_dir=server_dir,
                    snapshots_root=Path(settings.backup_storage_path) / "tier1",
                    backup_id=str(backup_id),
                    is_running=is_running,
                    locks_dir=layout.locks,
                )
                size_bytes = snap.size_bytes
                checksum = snap.checksum
                storage_path = snap.snapshot_dir
            else:
                archive_format = params.get("archive_format", "tar.zst")
                include_cas_jars = bool(params.get("include_cas_jars", False))
                encrypt = params.get("encrypt")
                cas = ArtifactCas(layout.cas)
                kek_path = (
                    Path(settings.master_kek_file)
                    if getattr(settings, "master_kek_file", None)
                    else None
                )
                arch = await create_tier2_archive(
                    server_id=str(server_id),
                    server_dir=server_dir,
                    backup_id=str(backup_id),
                    storage=storage,
                    archive_format=archive_format,
                    include_cas_jars=include_cas_jars,
                    encrypt=encrypt,
                    kek_file_path=kek_path,
                    cas=cas,
                )
                size_bytes = arch.size_bytes
                checksum = arch.checksum
                storage_path = arch.storage_path

            pruned_storage_paths: list[str] = []
            async with UnitOfWork(event_bus=event_bus) as uow:
                repo = SQLBackupRepository(uow.session)
                job = await repo.get_job(backup_id)
                job.mark_completed(
                    size_bytes=size_bytes,
                    checksum=checksum,
                    storage_path=storage_path,
                )
                await repo.save_job(job)
                await repo.prune_old_backups(
                    server_id, tier=tier, deleted_paths=pruned_storage_paths
                )
                for event in job.collect_events():
                    uow.add_event(event)
                await uow.commit()
            for old_path in pruned_storage_paths:
                try:
                    await storage.delete(old_path)
                except Exception as del_exc:
                    logger.warning(
                        "Failed deleting pruned backup artifact %s: %s", old_path, del_exc
                    )
        else:
            await saga.execute(
                backup_id=backup_id,
                server_id=server_id,
                storage=storage,
                encryption=encryption,
                backup_type=backup_type,
            )
    except BackupCancelledError as exc:
        logger.warning("Backup task cancelled: %s for server %s (%s)", backup_id, server_id, exc)
        async with UnitOfWork(event_bus=event_bus) as uow:
            repo = SQLBackupRepository(uow.session)
            job = await repo.get_job(backup_id)
            job.mark_failed_timeout(str(exc))
            await repo.save_job(job)
            if hasattr(job, "collect_events") and hasattr(uow, "add_event"):
                for event in job.collect_events():
                    uow.add_event(event)
            await uow.commit()
        clear_cancelled_backup(str(backup_id))
        return {
            "backup_id": str(backup_id),
            "server_id": str(server_id),
            "status": "failed_timeout",
        }
    except Exception as exc:
        logger.exception("Backup task failed: %s for server %s", backup_id, server_id)
        async with UnitOfWork(event_bus=event_bus) as uow:
            repo = SQLBackupRepository(uow.session)
            job = await repo.get_job(backup_id)
            if is_backup_cancelled(str(backup_id)):
                job.mark_failed_timeout("Backup cancelled due to timeout")
            else:
                reason = f"Backup task failed: {exc}" if str(exc) else "Backup task failed"
                job.mark_failed(reason)
            await repo.save_job(job)
            if hasattr(job, "collect_events") and hasattr(uow, "add_event"):
                for event in job.collect_events():
                    uow.add_event(event)
            await uow.commit()
        clear_cancelled_backup(str(backup_id))
        raise

    logger.info("Backup task completed: %s for server %s", backup_id, server_id)
    return {"backup_id": str(backup_id), "server_id": str(server_id)}
