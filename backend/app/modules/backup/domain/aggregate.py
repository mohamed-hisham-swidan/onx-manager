from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from app.modules.backup.domain.events import (
    BackupCompletedEvent,
    BackupDeletedEvent,
    BackupFailedEvent,
    BackupRestoredEvent,
    BackupStartedEvent,
)
from app.modules.shared.aggregate import AggregateRoot
from app.modules.shared.value_objects import BackupJobId, CronExpression, ServerId


class BackupType(Enum):
    FULL = "full"
    WORLDS = "worlds"
    WORLD = "world"
    NETHER = "nether"
    END = "end"
    PLUGINS = "plugins"
    CONFIG = "config"


class BackupStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class BackupJob(AggregateRoot):
    def __init__(
        self,
        backup_id: BackupJobId,
        server_id: ServerId,
        backup_type: BackupType,
        status: BackupStatus = BackupStatus.PENDING,
        size_bytes: int = 0,
        checksum: str = "",
        storage_path: str = "",
        error_message: str = "",
        created_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self._backup_id = backup_id
        self._server_id = server_id
        self._backup_type = backup_type
        self._status = status
        self._size_bytes = size_bytes
        self._checksum = checksum
        self._storage_path = storage_path
        self._error_message = error_message
        self._created_at = created_at or datetime.now(timezone.utc)
        self._completed_at = completed_at

    @property
    def backup_id(self) -> BackupJobId:
        return self._backup_id

    @property
    def server_id(self) -> ServerId:
        return self._server_id

    @property
    def backup_type(self) -> BackupType:
        return self._backup_type

    @property
    def status(self) -> BackupStatus:
        return self._status

    @property
    def size_bytes(self) -> int:
        return self._size_bytes

    @property
    def checksum(self) -> str:
        return self._checksum

    @property
    def storage_path(self) -> str:
        return self._storage_path

    @property
    def error_message(self) -> str:
        return self._error_message

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def completed_at(self) -> datetime | None:
        return self._completed_at

    @classmethod
    def create(cls, backup_id: BackupJobId, server_id: ServerId, backup_type: BackupType = BackupType.FULL) -> BackupJob:
        job = cls(backup_id=backup_id, server_id=server_id, backup_type=backup_type)
        job._add_event(BackupStartedEvent(backup_id=str(backup_id), server_id=str(server_id)))
        return job

    def mark_completed(self, size_bytes: int, checksum: str, storage_path: str = "") -> None:
        self._status = BackupStatus.COMPLETED
        self._size_bytes = size_bytes
        self._checksum = checksum
        if storage_path:
            self._storage_path = storage_path
        self._completed_at = datetime.now(timezone.utc)
        self._add_event(
            BackupCompletedEvent(
                backup_id=str(self._backup_id),
                server_id=str(self._server_id),
                size_bytes=size_bytes,
                checksum=checksum,
                storage_path=storage_path,
            ),
        )

    def mark_failed(self, reason: str) -> None:
        self._status = BackupStatus.FAILED
        self._error_message = reason
        self._completed_at = datetime.now(timezone.utc)
        self._add_event(
            BackupFailedEvent(
                backup_id=str(self._backup_id),
                server_id=str(self._server_id),
                reason=reason,
            ),
        )

    def mark_restored(self) -> None:
        self._add_event(
            BackupRestoredEvent(backup_id=str(self._backup_id), server_id=str(self._server_id)),
        )

    def mark_deleted(self) -> None:
        self._add_event(
            BackupDeletedEvent(backup_id=str(self._backup_id), server_id=str(self._server_id)),
        )


class BackupPolicy(AggregateRoot):
    def __init__(
        self,
        server_id: ServerId,
        schedule: CronExpression,
        retention_days: int = 30,
        backup_type: BackupType = BackupType.FULL,
        encryption_enabled: bool = True,
        max_backups: int = 50,
        enabled: bool = True,
    ) -> None:
        super().__init__()
        self._server_id = server_id
        self._schedule = schedule
        self._retention_days = retention_days
        self._backup_type = backup_type
        self._encryption_enabled = encryption_enabled
        self._max_backups = max_backups
        self._enabled = enabled

    @property
    def server_id(self) -> ServerId:
        return self._server_id

    @property
    def schedule(self) -> CronExpression:
        return self._schedule

    @property
    def retention_days(self) -> int:
        return self._retention_days

    @property
    def backup_type(self) -> BackupType:
        return self._backup_type

    @property
    def encryption_enabled(self) -> bool:
        return self._encryption_enabled

    @property
    def max_backups(self) -> int:
        return self._max_backups

    @property
    def enabled(self) -> bool:
        return self._enabled
