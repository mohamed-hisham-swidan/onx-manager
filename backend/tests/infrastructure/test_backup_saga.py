from __future__ import annotations

import hashlib
import io
import os
import tarfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.saga import SagaOrchestrator
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


async def _seed_pending_job(backup_id: BackupJobId, server_id: ServerId) -> None:
    from app.modules.backup.domain.aggregate import BackupJob

    async with database.session_factory() as session:
        job = BackupJob.create(
            backup_id=backup_id,
            server_id=server_id,
            backup_type=BackupType.FULL,
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
        expected_path = f"backups/{backup_id}.tar.gz.enc"
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
    async def test_saga_fails_when_world_missing(self, app_db, tmp_path) -> None:
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

        await _seed_pending_job(backup_id, server_id)

        saga = BackupSaga(SagaOrchestrator())
        await saga.execute(
            backup_id=backup_id,
            server_id=server_id,
            storage=storage,
            encryption=BackupEncryption(key=os.urandom(32)),
        )

        async with database.session_factory() as session:
            job = await SQLBackupRepository(session).get_job(backup_id)

        assert job.status == BackupStatus.FAILED
        assert job.size_bytes == 0
        assert not await storage.exists(f"backups/{backup_id}.tar.gz.enc")
