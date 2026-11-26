from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.exceptions import ValidationError
from app.core.persistence.db import database
from app.core.query_bus import Query, QueryHandler
from app.modules.backup.domain.aggregate import parse_backup_tier
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.server.infrastructure.models import ServerModel
from app.modules.shared.value_objects import ServerId


class BackupReadModel:
    def __init__(
        self,
        backup_id: str,
        server_id: str,
        backup_type: str,
        status: str,
        size_bytes: int,
        checksum: str,
        error_message: str,
        created_at: datetime,
        completed_at: datetime | None = None,
        tier: str = "tier_1",
        pinned: bool = False,
        server_name: str | None = None,
        server_deleted: bool = False,
    ) -> None:
        self.backup_id = backup_id
        self.server_id = server_id
        self.server_name = server_name
        self.server_deleted = server_deleted
        self.backup_type = backup_type
        self.status = status
        self.size_bytes = size_bytes
        self.checksum = checksum
        self.error_message = error_message
        self.created_at = created_at
        self.completed_at = completed_at
        self.tier = tier
        self.pinned = pinned

    @classmethod
    def from_domain(
        cls,
        job: Any,
        *,
        server_name: str | None = None,
        server_deleted: bool = False,
    ) -> BackupReadModel:
        raw_tier: Any = getattr(job, "tier", "tier_1")
        tier_val = raw_tier.value if hasattr(raw_tier, "value") else str(raw_tier)
        return cls(
            backup_id=str(job.backup_id),
            server_id=str(job.server_id),
            server_name=server_name,
            server_deleted=server_deleted,
            backup_type=job.backup_type.value,
            status=job.status.value,
            size_bytes=job.size_bytes,
            checksum=job.checksum,
            error_message=job.error_message,
            created_at=job.created_at,
            completed_at=job.completed_at,
            tier=tier_val,
            pinned=bool(getattr(job, "pinned", False)),
        )


class ListBackupsQuery(Query):
    server_id: str | None = None
    tier: str | None = None


class ListBackupsHandler(QueryHandler[ListBackupsQuery]):
    async def handle(self, query: ListBackupsQuery) -> list[BackupReadModel]:
        server_id = ServerId(query.server_id) if query.server_id else None
        resolved_tier = None
        if query.tier is not None:
            try:
                resolved_tier = parse_backup_tier(query.tier)
            except ValueError as exc:
                raise ValidationError(str(exc), field="tier") from exc
        async with database.session_factory() as session:
            repo: BackupRepository = SQLBackupRepository(session)
            jobs = await repo.list_jobs(server_id, tier=resolved_tier)
            if not jobs:
                return []

            server_ids = sorted({str(j.server_id) for j in jobs})
            stmt = select(ServerModel.id, ServerModel.name).where(
                ServerModel.id.in_(server_ids)
            )
            rows = (await session.execute(stmt)).all()
            server_names = {str(row[0]): row[1] for row in rows}

            return [
                BackupReadModel.from_domain(
                    j,
                    server_name=server_names.get(str(j.server_id)),
                    server_deleted=str(j.server_id) not in server_names,
                )
                for j in jobs
            ]
