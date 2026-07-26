from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.backup.domain.aggregate import BackupJob, BackupPolicy
from app.modules.shared.value_objects import BackupJobId, ServerId


class BackupRepository(ABC):
    @abstractmethod
    async def get_job(self, backup_id: BackupJobId) -> BackupJob:
        ...

    @abstractmethod
    async def list_jobs(self, server_id: ServerId | None = None) -> list[BackupJob]:
        ...

    @abstractmethod
    async def save_job(self, job: BackupJob) -> None:
        ...

    @abstractmethod
    async def delete_job(self, backup_id: BackupJobId) -> None:
        ...

    @abstractmethod
    async def get_policy(self, server_id: ServerId) -> BackupPolicy | None:
        ...

    @abstractmethod
    async def save_policy(self, policy: BackupPolicy) -> None:
        ...

    @abstractmethod
    async def delete_policy(self, server_id: ServerId) -> None:
        ...
