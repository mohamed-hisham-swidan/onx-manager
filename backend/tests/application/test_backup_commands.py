import hashlib
from unittest.mock import patch

import pytest

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.modules.backup.application.commands.create_backup import (
    CreateBackupCommand,
    CreateBackupHandler,
)
from app.modules.backup.application.commands.delete_backup import (
    DeleteBackupCommand,
    DeleteBackupHandler,
)
from app.modules.backup.application.commands.restore_backup import (
    RestoreBackupCommand,
    RestoreBackupHandler,
)
from app.modules.backup.application.commands.verify_backup import (
    VerifyBackupCommand,
    VerifyBackupHandler,
)
from app.modules.backup.domain.aggregate import BackupJob, BackupType
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.modules.storage.base import StorageBackend, StorageResult
from app.core.persistence.db import database


class FakeStorage(StorageBackend):
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def write(self, path: str, data: bytes) -> StorageResult:
        self._store[path] = data
        return StorageResult(path=path, size_bytes=len(data), checksum="")

    async def read(self, path: str) -> bytes:
        return self._store.get(path, b"")

    async def delete(self, path: str) -> bool:
        return self._store.pop(path, None) is not None

    async def exists(self, path: str) -> bool:
        return path in self._store

    async def list_files(self, prefix: str) -> list:
        return []

    async def info(self, path: str):
        return None

    async def copy(self, source: str, destination: str) -> StorageResult:
        data = await self.read(source)
        return await self.write(destination, data)


def _bus(event_bus: EventBus) -> CommandBus:
    return CommandBus()


@pytest.mark.usefixtures("init_test_db")
class TestCreateBackupHandler:
    @pytest.mark.asyncio
    async def test_create_backup(self, event_bus: EventBus) -> None:
        handler = CreateBackupHandler(event_bus)
        cmd = CreateBackupCommand(server_id="srv-1", backup_type="full")

        result = await handler.handle(cmd)

        assert result.success is True
        assert "backup_id" in result.data

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = await repo.get_job(BackupJobId(result.data["backup_id"]))
            assert str(job.server_id) == "srv-1"
            assert job.backup_type == BackupType.FULL

    @pytest.mark.asyncio
    async def test_create_backup_invalid_type(self, event_bus: EventBus) -> None:
        bus = _bus(event_bus)
        bus.register(CreateBackupCommand, CreateBackupHandler(event_bus))
        cmd = CreateBackupCommand(server_id="srv-1", backup_type="invalid")

        result = await bus.send(cmd)
        assert result.success is False


@pytest.mark.usefixtures("init_test_db")
class TestDeleteBackupHandler:
    @pytest.mark.asyncio
    async def test_delete_backup(self, event_bus: EventBus) -> None:
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = BackupJob.create(
                backup_id=BackupJobId("del-bak-1"),
                server_id=ServerId("srv-1"),
            )
            job.collect_events()
            await repo.save_job(job)
            await session.commit()

        handler = DeleteBackupHandler(event_bus)
        result = await handler.handle(DeleteBackupCommand(backup_id="del-bak-1"))

        assert result.success is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, event_bus: EventBus) -> None:
        bus = _bus(event_bus)
        bus.register(DeleteBackupCommand, DeleteBackupHandler(event_bus))
        result = await bus.send(DeleteBackupCommand(backup_id="nonexistent"))
        assert result.success is False


@pytest.mark.usefixtures("init_test_db")
class TestRestoreBackupHandler:
    @pytest.mark.asyncio
    async def test_restore_backup(self, event_bus: EventBus) -> None:
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = BackupJob.create(
                backup_id=BackupJobId("res-bak-1"),
                server_id=ServerId("srv-1"),
            )
            job.mark_completed(size_bytes=1000, checksum="abc123")
            await repo.save_job(job)
            await session.commit()

        handler = RestoreBackupHandler(event_bus)
        result = await handler.handle(RestoreBackupCommand(backup_id="res-bak-1"))

        assert result.success is True

    @pytest.mark.asyncio
    async def test_restore_nonexistent(self, event_bus: EventBus) -> None:
        bus = _bus(event_bus)
        bus.register(RestoreBackupCommand, RestoreBackupHandler(event_bus))
        result = await bus.send(RestoreBackupCommand(backup_id="nonexistent"))
        assert result.success is False


@pytest.mark.usefixtures("init_test_db")
class TestVerifyBackupHandler:
    @pytest.mark.asyncio
    async def test_verify_valid_backup(self, event_bus: EventBus) -> None:
        artifact = b"encrypted-backup-data"
        checksum = hashlib.sha256(artifact).hexdigest()
        path = "vrf-bak-1.tar.gz.enc"

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = BackupJob.create(
                backup_id=BackupJobId("vrf-bak-1"),
                server_id=ServerId("srv-1"),
            )
            job.mark_completed(
                size_bytes=len(artifact),
                checksum=checksum,
                storage_path=path,
            )
            await repo.save_job(job)
            await session.commit()

        fake_storage = FakeStorage()
        await fake_storage.write(path, artifact)

        with patch(
            "app.modules.backup.application.commands.verify_backup.build_storage_backend",
            return_value=fake_storage,
        ):
            handler = VerifyBackupHandler(event_bus)
            result = await handler.handle(VerifyBackupCommand(backup_id="vrf-bak-1"))

        assert result.success is True
        assert result.data["valid"] is True
        assert result.data["checksum_valid"] is True
        assert result.data["size_valid"] is True

    @pytest.mark.asyncio
    async def test_verify_invalid_when_artifact_missing(self, event_bus: EventBus) -> None:
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = BackupJob.create(
                backup_id=BackupJobId("vrf-bak-2"),
                server_id=ServerId("srv-1"),
            )
            job.mark_completed(
                size_bytes=5000,
                checksum="sha256-abc",
                storage_path="missing.tar.gz.enc",
            )
            await repo.save_job(job)
            await session.commit()

        with patch(
            "app.modules.backup.application.commands.verify_backup.build_storage_backend",
            return_value=FakeStorage(),
        ):
            handler = VerifyBackupHandler(event_bus)
            result = await handler.handle(VerifyBackupCommand(backup_id="vrf-bak-2"))

        assert result.success is True
        assert result.data["valid"] is False
        assert result.data["artifact_present"] is False

    @pytest.mark.asyncio
    async def test_verify_nonexistent(self, event_bus: EventBus) -> None:
        bus = _bus(event_bus)
        bus.register(VerifyBackupCommand, VerifyBackupHandler(event_bus))
        result = await bus.send(VerifyBackupCommand(backup_id="nonexistent"))
        assert result.success is False
