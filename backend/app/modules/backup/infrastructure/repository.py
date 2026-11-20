from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backup.domain.aggregate import BackupJob, BackupPolicy, BackupStatus, BackupType
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.models import (
    BackupJobModel,
    BackupPolicyModel,
    PendingRestoreModel,
)
from app.modules.shared.value_objects import BackupJobId, CronExpression, ServerId


class SQLBackupRepository(BackupRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_job(self, backup_id: BackupJobId) -> BackupJob:
        model = await self._session.get(BackupJobModel, str(backup_id))
        if model is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(f"Backup job '{backup_id}' not found")
        return self._job_model_to_domain(model)

    async def list_jobs(self, server_id: ServerId | None = None) -> list[BackupJob]:
        stmt = select(BackupJobModel).order_by(BackupJobModel.created_at.desc())
        if server_id:
            stmt = stmt.where(BackupJobModel.server_id == str(server_id))
        result = await self._session.execute(stmt)
        return [self._job_model_to_domain(m) for m in result.scalars().all()]

    async def save_job(self, job: BackupJob) -> None:
        model = await self._session.get(BackupJobModel, str(job.backup_id))
        if model is None:
            model = BackupJobModel(id=str(job.backup_id))
            self._session.add(model)

        model.server_id = str(job.server_id)
        model.backup_type = job.backup_type.value
        model.status = job.status.value
        model.size_bytes = job.size_bytes
        model.checksum = job.checksum
        model.storage_path = job.storage_path or None
        model.error_message = job.error_message or None
        model.completed_at = job.completed_at
        model.pinned = bool(job.pinned)
        await self._session.flush()

    async def delete_job(self, backup_id: BackupJobId) -> None:
        model = await self._session.get(BackupJobModel, str(backup_id))
        if model is None:
            return
        if bool(model.pinned):
            from app.core.exceptions import BackupPinnedError

            raise BackupPinnedError(str(backup_id))
        await self._session.delete(model)
        await self._session.flush()

    async def set_pinned(self, backup_id: BackupJobId, pinned: bool) -> BackupJob:
        model = await self._session.get(BackupJobModel, str(backup_id))
        if model is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(f"Backup job '{backup_id}' not found")
        model.pinned = bool(pinned)
        await self._session.flush()
        return self._job_model_to_domain(model)

    async def prune_old_backups(
        self,
        server_id: ServerId,
        *,
        max_backups: int | None = None,
        retention_days: int | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        from app.core.exceptions import ValidationError

        if max_backups is not None and max_backups < 0:
            raise ValidationError("max_backups must be non-negative", field="max_backups")
        if retention_days is not None and retention_days < 0:
            raise ValidationError("retention_days must be non-negative", field="retention_days")

        if max_backups is None and retention_days is None:
            policy = await self._session.get(BackupPolicyModel, str(server_id))
            if policy is None:
                return []
            max_backups = policy.max_backups
            retention_days = policy.retention_days

        result = await self._session.execute(
            select(BackupJobModel)
            .where(BackupJobModel.server_id == str(server_id))
            .order_by(BackupJobModel.created_at.desc())
        )
        rows = [row for row in result.scalars().all() if not bool(row.pinned)]
        moment = now or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        cutoff = (
            moment - timedelta(days=retention_days) if retention_days is not None else None
        )

        to_delete: set[str] = set()
        if cutoff is not None:
            for row in rows:
                created_at = row.created_at
                if created_at is None:
                    continue
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                if created_at < cutoff:
                    to_delete.add(row.id)

        if max_backups is not None:
            survivors = [row for row in rows if row.id not in to_delete]
            for row in survivors[max_backups:]:
                to_delete.add(row.id)

        if not to_delete:
            return []
        await self._session.execute(
            delete(BackupJobModel).where(BackupJobModel.id.in_(to_delete))
        )
        await self._session.flush()
        return sorted(to_delete)

    async def get_policy(self, server_id: ServerId) -> BackupPolicy | None:
        model = await self._session.get(BackupPolicyModel, str(server_id))
        if model is None:
            return None
        return BackupPolicy(
            server_id=ServerId(model.server_id),
            schedule=CronExpression(model.schedule),
            retention_days=model.retention_days,
            backup_type=BackupType(model.backup_type),
            encryption_enabled=model.encryption_enabled,
            max_backups=model.max_backups,
            enabled=model.enabled,
        )

    async def save_policy(self, policy: BackupPolicy) -> None:
        model = await self._session.get(BackupPolicyModel, str(policy.server_id))
        if model is None:
            model = BackupPolicyModel(server_id=str(policy.server_id))
            self._session.add(model)

        model.schedule = str(policy.schedule)
        model.retention_days = policy.retention_days
        model.backup_type = policy.backup_type.value
        model.encryption_enabled = policy.encryption_enabled
        model.max_backups = policy.max_backups
        model.enabled = policy.enabled
        await self._session.flush()

    async def delete_policy(self, server_id: ServerId) -> None:
        model = await self._session.get(BackupPolicyModel, str(server_id))
        if model:
            await self._session.delete(model)
            await self._session.flush()

    async def get_pending_restore(self, server_id: ServerId) -> tuple[str, datetime] | None:
        model = await self._session.get(PendingRestoreModel, str(server_id))
        if model is None:
            return None
        return model.backup_id, model.requested_at

    async def upsert_pending_restore(
        self,
        server_id: ServerId,
        backup_id: BackupJobId,
        requested_at: datetime,
    ) -> None:
        model = await self._session.get(PendingRestoreModel, str(server_id))
        if model is None:
            model = PendingRestoreModel(server_id=str(server_id))
            self._session.add(model)
        model.backup_id = str(backup_id)
        model.requested_at = requested_at
        await self._session.flush()

    async def delete_pending_restore(self, server_id: ServerId) -> None:
        model = await self._session.get(PendingRestoreModel, str(server_id))
        if model:
            await self._session.delete(model)
            await self._session.flush()

    def _job_model_to_domain(self, model: BackupJobModel) -> BackupJob:
        return BackupJob(
            backup_id=BackupJobId(model.id),
            server_id=ServerId(model.server_id),
            backup_type=BackupType(model.backup_type),
            status=BackupStatus(model.status),
            size_bytes=model.size_bytes,
            checksum=model.checksum,
            storage_path=model.storage_path or "",
            error_message=model.error_message or "",
            created_at=model.created_at,
            completed_at=model.completed_at,
            pinned=bool(model.pinned),
        )
