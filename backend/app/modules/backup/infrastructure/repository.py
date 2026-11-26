from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backup.domain.aggregate import (
    BackupJob,
    BackupPolicy,
    BackupStatus,
    BackupTier,
    BackupType,
)
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

    async def list_jobs(
        self,
        server_id: ServerId | None = None,
        *,
        tier: BackupTier | None = None,
    ) -> list[BackupJob]:
        stmt = select(BackupJobModel).order_by(BackupJobModel.created_at.desc())
        if server_id:
            stmt = stmt.where(BackupJobModel.server_id == str(server_id))
        if tier is not None:
            stmt = stmt.where(BackupJobModel.tier == tier.value)
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
        model.tier = job.tier.value
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
        tier: BackupTier | None = None,
        tier1_keep: int = 5,
        tier2_daily: int = 7,
        tier2_weekly: int = 4,
        deleted_paths: list[str] | None = None,
    ) -> list[str]:
        from app.core.exceptions import ValidationError

        if max_backups is not None and max_backups < 0:
            raise ValidationError("max_backups must be non-negative", field="max_backups")
        if retention_days is not None and retention_days < 0:
            raise ValidationError("retention_days must be non-negative", field="retention_days")

        moment = now or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)

        if tier is not None:
            stmt = (
                select(BackupJobModel)
                .where(
                    BackupJobModel.server_id == str(server_id),
                    BackupJobModel.tier == tier.value,
                    BackupJobModel.status == BackupStatus.COMPLETED.value,
                )
                .order_by(BackupJobModel.created_at.desc())
            )
            result = await self._session.execute(stmt)
            unpinned = [row for row in result.scalars().all() if not bool(row.pinned)]

            to_delete: set[str] = set()
            if tier == BackupTier.TIER_1:
                if tier1_keep < 0:
                    raise ValidationError("tier1_keep must be non-negative", field="tier1_keep")
                for row in unpinned[tier1_keep:]:
                    to_delete.add(str(row.id))
            else:
                if tier2_daily < 0 or tier2_weekly < 0:
                    raise ValidationError(
                        "tier2 retention counts must be non-negative",
                        field="tier2_daily",
                    )
                daily_buckets = {
                    (moment - timedelta(days=offset)).date()
                    for offset in range(tier2_daily)
                }
                weekly_buckets = {
                    (moment - timedelta(weeks=offset)).isocalendar()[:2]
                    for offset in range(tier2_weekly)
                }
                kept_days: set[object] = set()
                kept_weeks: set[tuple[int, int]] = set()
                keep_ids: set[str] = set()

                for row in unpinned:
                    created_at = row.created_at
                    if created_at is None:
                        continue
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=UTC)
                    day_key = created_at.date()
                    iso = created_at.isocalendar()
                    week_key = (iso[0], iso[1])

                    keep_for_day = day_key in daily_buckets and day_key not in kept_days
                    keep_for_week = week_key in weekly_buckets and week_key not in kept_weeks
                    if keep_for_day:
                        kept_days.add(day_key)
                    if keep_for_week:
                        kept_weeks.add(week_key)
                    if keep_for_day or keep_for_week:
                        keep_ids.add(str(row.id))

                for row in unpinned:
                    if str(row.id) not in keep_ids:
                        to_delete.add(str(row.id))

            if not to_delete:
                return []
            if deleted_paths is not None:
                for row in unpinned:
                    if str(row.id) in to_delete and row.storage_path:
                        deleted_paths.append(str(row.storage_path))
            await self._session.execute(
                delete(BackupJobModel).where(BackupJobModel.id.in_(to_delete))
            )
            await self._session.flush()
            return sorted(to_delete)

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
        cutoff = (
            moment - timedelta(days=retention_days) if retention_days is not None else None
        )

        to_delete = set()
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
        if deleted_paths is not None:
            for row in rows:
                if row.id in to_delete and row.storage_path:
                    deleted_paths.append(str(row.storage_path))
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
            tier=BackupTier(getattr(model, "tier", None) or "tier_1"),
        )
