from __future__ import annotations

import hashlib
import io
import os
import tarfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.event_bus import EventBus
from app.core.exceptions import NotFoundError
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.saga import SagaOrchestrator
from app.modules.backup.application.commands.delete_backup import (
    DeleteBackupCommand,
    DeleteBackupHandler,
)
from app.modules.backup.domain.aggregate import BackupJob, BackupStatus, BackupType
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.server.domain.aggregate import Server, ServerStatus
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
from app.modules.server.domain.value_objects import RuntimeInfo
from app.modules.shared.value_objects import BackupJobId, MinecraftVersion, ServerId
from app.modules.storage.encryption import BackupEncryption
from app.modules.storage.local import LocalStorage
from app.services.backup_orchestrator import BackupSaga


@pytest.fixture
async def app_db():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False,
    )
    yield
    await engine.dispose()
    database._engine = None
    database._session_factory = None


def _build_server(server_id: ServerId, server_dir: str) -> Server:
    server = Server.create(
        server_id=server_id,
        name="saga-test-server",
        server_type=ServerType.VANILLA,
        minecraft_version=MinecraftVersion.parse("1.21"),
        memory=MemoryAllocation(min_mb=1024, max_mb=2048),
        java_args=JavaArguments([]),
        properties=ServerProperties(
            port=PortNumber(25565),
            gamemode="survival",
            difficulty="easy",
        ),
        deployment=ServerDeployment(
            location_type=LocationType.LOCAL,
            location_uri="",
            root_path=server_dir,
            working_directory=".",
            startup_jar="server.jar",
        ),
    )
    server._status = ServerStatus.STOPPED
    return server


def _seed_world(server_dir: str) -> None:
    world_dir = Path(server_dir) / "world" / "region"
    world_dir.mkdir(parents=True, exist_ok=True)
    (world_dir / "r.0.0.mca").write_bytes(b"\x00" * 4096)
    (Path(server_dir) / "server.properties").write_text(
        "motd=saga test\ngamemode=survival\n",
        encoding="utf-8",
    )
    (Path(server_dir) / "eula.txt").write_text("eula=true\n", encoding="utf-8")


async def _seed_pending_job(
    backup_id: BackupJobId, server_id: ServerId, backup_type: BackupType = BackupType.FULL,
) -> None:
    from app.modules.backup.domain.aggregate import BackupJob

    async with database.session_factory() as session:
        job = BackupJob.create(
            backup_id=backup_id,
            server_id=server_id,
            backup_type=backup_type,
        )
        await SQLBackupRepository(session).save_job(job)
        await session.commit()


class TestBackupSaga:
    @pytest.mark.asyncio
    async def test_saga_compresses_encrypts_uploads_and_verifies(
        self, app_db, tmp_path,
    ) -> None:
        server_dir = str(tmp_path / "server")
        _seed_world(server_dir)
        server_id = ServerId(uuid.uuid4().hex)
        backup_id = BackupJobId()
        storage = LocalStorage(str(tmp_path / "backups"))
        encryption = BackupEncryption(key=os.urandom(32))

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(_build_server(server_id, server_dir))
            await session.commit()

        await _seed_pending_job(backup_id, server_id)

        saga = BackupSaga(SagaOrchestrator())
        await saga.execute(
            backup_id=backup_id,
            server_id=server_id,
            storage=storage,
            encryption=encryption,
        )

        async with database.session_factory() as session:
            job = await SQLBackupRepository(session).get_job(backup_id)

        assert job.status == BackupStatus.COMPLETED
        assert job.backup_type == BackupType.FULL
        assert job.size_bytes > 0
        expected_path = f"{backup_id}.tar.gz.enc"
        assert job.storage_path == expected_path

        artifact = await storage.read(expected_path)
        assert len(artifact) == job.size_bytes
        assert hashlib.sha256(artifact).hexdigest() == job.checksum

        decrypted = encryption.decrypt(artifact)
        with tarfile.open(fileobj=io.BytesIO(decrypted), mode="r:gz") as tar:
            names = tar.getnames()
            assert "world" in names
            assert "world/region/r.0.0.mca" in names
            assert "server.properties" in names
            assert "eula.txt" in names

    @pytest.mark.asyncio
    async def test_full_backup_succeeds_when_world_missing(self, app_db, tmp_path) -> None:
        server_dir = str(tmp_path / "server")
        Path(server_dir).mkdir(parents=True, exist_ok=True)
        (Path(server_dir) / "server.properties").write_text(
            "motd=no world here\n", encoding="utf-8",
        )
        server_id = ServerId(uuid.uuid4().hex)
        backup_id = BackupJobId()
        storage = LocalStorage(str(tmp_path / "backups"))
        encryption = BackupEncryption(key=os.urandom(32))

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(_build_server(server_id, server_dir))
            await session.commit()

        await _seed_pending_job(backup_id, server_id, BackupType.FULL)

        saga = BackupSaga(SagaOrchestrator())
        await saga.execute(
            backup_id=backup_id,
            server_id=server_id,
            storage=storage,
            encryption=encryption,
            backup_type=BackupType.FULL,
        )

        async with database.session_factory() as session:
            job = await SQLBackupRepository(session).get_job(backup_id)

        assert job.status == BackupStatus.COMPLETED
        assert job.size_bytes > 0
        artifact = await storage.read(f"{backup_id}.tar.gz.enc")
        decrypted = encryption.decrypt(artifact)
        with tarfile.open(fileobj=io.BytesIO(decrypted), mode="r:gz") as tar:
            names = tar.getnames()
            assert "world" not in names
            assert "server.properties" in names

    @pytest.mark.asyncio
    async def test_world_backup_fails_when_world_missing(self, app_db, tmp_path) -> None:
        server_dir = str(tmp_path / "server")
        Path(server_dir).mkdir(parents=True, exist_ok=True)
        (Path(server_dir) / "server.properties").write_text(
            "motd=no world here\n", encoding="utf-8",
        )
        server_id = ServerId(uuid.uuid4().hex)
        backup_id = BackupJobId()
        storage = LocalStorage(str(tmp_path / "backups"))

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(_build_server(server_id, server_dir))
            await session.commit()

        await _seed_pending_job(backup_id, server_id, BackupType.WORLD)

        saga = BackupSaga(SagaOrchestrator())
        await saga.execute(
            backup_id=backup_id,
            server_id=server_id,
            storage=storage,
            encryption=BackupEncryption(key=os.urandom(32)),
            backup_type=BackupType.WORLD,
        )

        async with database.session_factory() as session:
            job = await SQLBackupRepository(session).get_job(backup_id)

        assert job.status == BackupStatus.FAILED
        assert job.size_bytes == 0
        assert not await storage.exists(f"{backup_id}.tar.gz.enc")


class TestDeleteBackupHandler:
    async def _seed_completed_job(self, backup_id: BackupJobId, server_id: ServerId, path: str) -> None:
        async with database.session_factory() as session:
            job = BackupJob.create(
                backup_id=backup_id,
                server_id=server_id,
                backup_type=BackupType.FULL,
            )
            job.mark_completed(size_bytes=100, checksum="deadbeef", storage_path=path)
            await SQLBackupRepository(session).save_job(job)
            await session.commit()

    @pytest.mark.asyncio
    async def test_delete_backup_deletes_artifact_and_row(self, app_db, tmp_path) -> None:
        storage = LocalStorage(str(tmp_path / "backups"))
        server_id = ServerId(uuid.uuid4().hex)
        backup_id = BackupJobId()
        path = f"{backup_id}.tar.gz.enc"
        await storage.write(path, b"x" * 100)
        await self._seed_completed_job(backup_id, server_id, path)

        with patch(
            "app.modules.backup.application.commands.delete_backup.build_storage_backend",
            return_value=storage,
        ):
            handler = DeleteBackupHandler(EventBus())
            result = await handler.handle(DeleteBackupCommand(backup_id=str(backup_id)))

        assert result.success is True
        assert not await storage.exists(path)
        async with database.session_factory() as session:
            with pytest.raises(NotFoundError):
                await SQLBackupRepository(session).get_job(backup_id)

    @pytest.mark.asyncio
    async def test_delete_backup_keeps_row_when_artifact_delete_fails(self, app_db, tmp_path) -> None:
        server_id = ServerId(uuid.uuid4().hex)
        backup_id = BackupJobId()
        path = f"{backup_id}.tar.gz.enc"
        await self._seed_completed_job(backup_id, server_id, path)

        mock_storage = AsyncMock()
        mock_storage.delete.side_effect = OSError("disk full")

        with patch(
            "app.modules.backup.application.commands.delete_backup.build_storage_backend",
            return_value=mock_storage,
        ):
            handler = DeleteBackupHandler(EventBus())
            result = await handler.handle(DeleteBackupCommand(backup_id=str(backup_id)))

        assert result.success is False
        assert path in result.error
        assert "disk full" in result.error
        async with database.session_factory() as session:
            job = await SQLBackupRepository(session).get_job(backup_id)
            assert job.storage_path == path


class _FakeProvider:
    def __init__(self, console_responses: list[list[str]]) -> None:
        self.commands: list[str] = []
        self._responses = list(console_responses)

    async def execute_command(self, handle, command: str) -> str:
        self.commands.append(command)
        return ""

    async def console(self, handle, tail: int = 100) -> list[str]:
        if self._responses:
            return self._responses.pop(0)
        return []


def _build_running_server(server_id: ServerId, server_dir: str) -> Server:
    server = _build_server(server_id, server_dir)
    server._status = ServerStatus.RUNNING
    server._runtime = RuntimeInfo(
        status="running",
        provider="local",
        host="127.0.0.1",
        port=25566,
        pid=12345,
        external_id="onx-save-test-session",
    )
    return server


class TestSaveAllOnRunningServer:
    @pytest.mark.asyncio
    async def test_save_world_confirmed_backup_proceeds(self, app_db, tmp_path) -> None:
        server_dir = str(tmp_path / "server")
        _seed_world(server_dir)
        server_id = ServerId(uuid.uuid4().hex)
        backup_id = BackupJobId()
        storage = LocalStorage(str(tmp_path / "backups"))
        encryption = BackupEncryption(key=os.urandom(32))

        fake = _FakeProvider(
            [
                ["[Server thread/INFO]: Saving chunks for level 'world'/overworld"],
                ["[Server thread/INFO]: Saved the game"],
            ],
        )

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(_build_running_server(server_id, server_dir))
            await session.commit()
        await _seed_pending_job(backup_id, server_id)

        saga = BackupSaga(SagaOrchestrator())
        with patch(
            "app.modules.server.infrastructure.providers.provider_factory"
        ) as mock_factory:
            mock_factory.get.return_value = fake
            await saga.execute(
                backup_id=backup_id,
                server_id=server_id,
                storage=storage,
                encryption=encryption,
            )

        assert fake.commands == ["save-all"]
        async with database.session_factory() as session:
            job = await SQLBackupRepository(session).get_job(backup_id)
        assert job.status == BackupStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_save_world_timeout_marks_job_failed(self, app_db, tmp_path) -> None:
        server_dir = str(tmp_path / "server")
        _seed_world(server_dir)
        server_id = ServerId(uuid.uuid4().hex)
        backup_id = BackupJobId()
        storage = LocalStorage(str(tmp_path / "backups"))

        fake = _FakeProvider(
            [["[Server thread/INFO]: Saving chunks for level 'world'/overworld"]],
        )

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(_build_running_server(server_id, server_dir))
            await session.commit()
        await _seed_pending_job(backup_id, server_id)

        saga = BackupSaga(SagaOrchestrator())
        with patch(
            "app.modules.server.infrastructure.providers.provider_factory"
        ) as mock_factory, patch(
            "app.services.backup_orchestrator.SAVE_ALL_CONFIRMATION_TIMEOUT_S",
            0.6,
        ), patch(
            "app.services.backup_orchestrator.SAVE_ALL_POLL_INTERVAL_S",
            0.1,
        ):
            mock_factory.get.return_value = fake
            await saga.execute(
                backup_id=backup_id,
                server_id=server_id,
                storage=storage,
                encryption=BackupEncryption(key=os.urandom(32)),
            )

        assert fake.commands == ["save-all"]
        async with database.session_factory() as session:
            job = await SQLBackupRepository(session).get_job(backup_id)
        assert job.status == BackupStatus.FAILED
        assert job.size_bytes == 0
        assert "save_world" in job.error_message
