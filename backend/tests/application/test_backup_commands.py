import hashlib
from unittest.mock import AsyncMock, patch

import pytest

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.db import database
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
from app.tasks.queue import get_task_queue


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

    @pytest.mark.asyncio
    async def test_create_backup_enqueue_failure_marks_job_failed(
        self, event_bus: EventBus
    ) -> None:
        failing_queue = get_task_queue()
        failing_queue.enqueue = AsyncMock(side_effect=RuntimeError("queue down"))

        handler = CreateBackupHandler(event_bus)
        cmd = CreateBackupCommand(server_id="srv-1", backup_type="full")

        result = await handler.handle(cmd)

        assert result.success is False
        assert result.error_code == "BACKUP_ENQUEUE_FAILED"
        assert "queue down" in (result.error or "")

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            jobs = await repo.list_jobs()
            assert jobs, "expected at least one backup job"
            job = jobs[0]
            assert job.status.value == "failed"
            assert "enqueue failed" in (job.error_message or "")


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
    async def _create_server(
        self, server_id: str, status: str = "created", with_deployment: bool = True
    ) -> None:
        from app.modules.server.domain.aggregate import Server
        from app.modules.server.domain.value_objects import (
            JavaArguments,
            LocationType,
            MemoryAllocation,
            PortNumber,
            ServerDeployment,
            ServerProperties,
            ServerType,
        )
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.shared.value_objects import MinecraftVersion

        deployment = None
        if with_deployment:
            deployment = ServerDeployment(
                location_type=LocationType.LOCAL,
                root_path=f"/tmp/onx-test/{server_id}",
                working_directory=".",
            )
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = Server.create(
                server_id=ServerId(server_id),
                name=f"Server {server_id}",
                server_type=ServerType.VANILLA,
                minecraft_version=MinecraftVersion.parse("1.21"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments(),
                properties=ServerProperties(port=PortNumber(25565)),
                deployment=deployment,
            )
            if status == "running":
                server.start()
                server.mark_running(pid=100, port=25565)
            elif status == "crashed":
                server.start()
                server.crash(exit_code=-1, last_log_lines=["boom"])
            elif status == "stopped":
                server.start()
                server.mark_running(pid=100, port=25565)
                server.stop(reason="test")
                server.mark_stopped()
            server.collect_events()
            await repo.save(server)
            await session.commit()

    async def _create_job(
        self, backup_id: str, server_id: str, storage_path: str = "bak.tar.gz.enc"
    ) -> None:
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = BackupJob.create(
                backup_id=BackupJobId(backup_id),
                server_id=ServerId(server_id),
            )
            job.mark_completed(size_bytes=1000, checksum="abc123", storage_path=storage_path)
            await repo.save_job(job)
            await session.commit()

    async def _pending(self, server_id: str) -> tuple[str, object] | None:
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            return await repo.get_pending_restore(ServerId(server_id))

    @pytest.mark.asyncio
    async def test_restore_deferred_when_server_running(self, event_bus: EventBus) -> None:
        await self._create_server("res-srv-running", status="running")
        await self._create_job("res-bak-deferred", "res-srv-running")

        with patch(
            "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
            AsyncMock(return_value=["world"]),
        ) as mock_restore:
            handler = RestoreBackupHandler(event_bus)
            result = await handler.handle(RestoreBackupCommand(backup_id="res-bak-deferred"))

        assert result.success is True
        assert result.data["deferred"] is True
        assert result.data["server_id"] == "res-srv-running"
        mock_restore.assert_not_awaited()
        pending = await self._pending("res-srv-running")
        assert pending is not None
        assert pending[0] == "res-bak-deferred"

    @pytest.mark.asyncio
    async def test_restore_deferred_when_server_crashed(self, event_bus: EventBus) -> None:
        await self._create_server("res-srv-crashed", status="crashed")
        await self._create_job("res-bak-crashed", "res-srv-crashed")

        handler = RestoreBackupHandler(event_bus)
        result = await handler.handle(RestoreBackupCommand(backup_id="res-bak-crashed"))

        assert result.success is True
        assert result.data["deferred"] is True
        pending = await self._pending("res-srv-crashed")
        assert pending is not None

    @pytest.mark.asyncio
    async def test_restore_immediate_when_server_stopped(self, event_bus: EventBus) -> None:
        await self._create_server("res-srv-stopped", status="stopped")
        await self._create_job("res-bak-immediate", "res-srv-stopped")

        with patch(
            "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
            AsyncMock(return_value=["world", "world_nether"]),
        ):
            handler = RestoreBackupHandler(event_bus)
            result = await handler.handle(RestoreBackupCommand(backup_id="res-bak-immediate"))

        assert result.success is True
        assert result.data["deferred"] is False
        assert result.data["restored_items"] == ["world", "world_nether"]
        assert await self._pending("res-srv-stopped") is None

    @pytest.mark.asyncio
    async def test_restore_immediate_when_server_created(self, event_bus: EventBus) -> None:
        await self._create_server("res-srv-created", status="created")
        await self._create_job("res-bak-created", "res-srv-created")

        with patch(
            "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
            AsyncMock(return_value=["world"]),
        ):
            handler = RestoreBackupHandler(event_bus)
            result = await handler.handle(RestoreBackupCommand(backup_id="res-bak-created"))

        assert result.success is True
        assert result.data["deferred"] is False

    @pytest.mark.asyncio
    async def test_restore_uses_fresh_deployment_config(self, event_bus: EventBus) -> None:
        """ISS-NEW-002: Re-fetch deployment before perform_safe_restore to avoid stale config."""
        from app.modules.server.domain.value_objects import LocationType, ServerDeployment
        from app.modules.server.infrastructure.repository import SQLServerRepository

        server_id = "res-srv-fresh-config"
        await self._create_server(server_id, status="stopped")
        await self._create_job("res-bak-fresh", server_id)

        updated_root = "/tmp/onx-test/updated-path"
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = await repo.get(ServerId(server_id))
            server.update_deployment(
                ServerDeployment(
                    location_type=LocationType.LOCAL,
                    root_path=updated_root,
                    working_directory=".",
                    primary_world="my_custom_world",
                )
            )
            await repo.save(server)
            await session.commit()

        captured_args = {}

        async def fake_restore(_backup_id, server_dir, base_world="world"):
            captured_args["server_dir"] = server_dir
            captured_args["base_world"] = base_world
            return ["my_custom_world"]

        with patch(
            "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
            side_effect=fake_restore,
        ):
            handler = RestoreBackupHandler(event_bus)
            result = await handler.handle(RestoreBackupCommand(backup_id="res-bak-fresh"))

        assert result.success is True
        assert captured_args["server_dir"] == updated_root
        assert captured_args["base_world"] == "my_custom_world"

    @pytest.mark.asyncio
    async def test_restore_failure_reported(self, event_bus: EventBus) -> None:
        from app.modules.backup.application.restore_service import RestoreError

        await self._create_server("res-srv-fail", status="stopped")
        await self._create_job("res-bak-fail", "res-srv-fail")

        with patch(
            "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
            AsyncMock(side_effect=RestoreError("checksum mismatch")),
        ):
            handler = RestoreBackupHandler(event_bus)
            result = await handler.handle(RestoreBackupCommand(backup_id="res-bak-fail"))

        assert result.success is False
        assert result.error_code == "RESTORE_FAILED"
        assert "checksum mismatch" in (result.error or "")

    @pytest.mark.asyncio
    async def test_restore_missing_artifact_rejected(self, event_bus: EventBus) -> None:
        await self._create_server("res-srv-noart", status="stopped")

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = BackupJob.create(
                backup_id=BackupJobId("res-bak-noart"),
                server_id=ServerId("res-srv-noart"),
            )
            job.mark_completed(size_bytes=1000, checksum="abc123", storage_path="")
            await repo.save_job(job)
            await session.commit()

        with patch(
            "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
            AsyncMock(return_value=["world"]),
        ) as mock_restore:
            handler = RestoreBackupHandler(event_bus)
            result = await handler.handle(RestoreBackupCommand(backup_id="res-bak-noart"))

        assert result.success is False
        assert result.error_code == "BACKUP_STORAGE_MISSING"
        mock_restore.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_restore_without_deployment_rejected(self, event_bus: EventBus) -> None:
        await self._create_server("res-srv-nodeploy", status="stopped", with_deployment=False)
        await self._create_job("res-bak-nodeploy", "res-srv-nodeploy")

        handler = RestoreBackupHandler(event_bus)
        result = await handler.handle(RestoreBackupCommand(backup_id="res-bak-nodeploy"))

        assert result.success is False
        assert result.error_code == "NO_DEPLOYMENT"

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
