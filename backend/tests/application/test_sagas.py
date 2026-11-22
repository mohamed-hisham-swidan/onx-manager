import os

import pytest

from app.core.persistence.db import database
from app.core.saga import SagaOrchestrator
from app.modules.backup.domain.aggregate import BackupJob
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
from app.modules.server.infrastructure.providers.base import (
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import BackupJobId, MinecraftVersion, ServerId
from app.modules.storage.base import StorageBackend, StorageResult
from app.modules.storage.encryption import BackupEncryption
from app.services.backup_orchestrator import BackupSaga
from app.services.deployment_orchestrator import DeploymentOrchestrator
from app.services.server_orchestrator import DeploymentSaga, RestartSaga


class FakeProvider(ServerProvider):
    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.status_result = ServerRuntimeStatus.RUNNING

    @property
    def provider_type(self) -> str:
        return "fake"

    async def ping(self) -> bool:
        return True

    async def start(self, server_id: str, config: dict) -> object:
        self.started.append(server_id)
        from app.modules.server.infrastructure.providers.base import DeploymentResult

        return DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="localhost",
            port=25565,
            pid=12345,
        )

    async def stop(self, handle: ServerHandle, force: bool = False) -> None:
        self.stopped.append(handle.server_id)

    async def status(self, handle: ServerHandle) -> ServerRuntimeStatus:
        return self.status_result

    async def console(self, handle: ServerHandle, tail: int = 100) -> list[str]:
        return ["[info] Server is running"]

    async def execute_command(self, handle: ServerHandle, command: str) -> str:
        return "ok"

    async def destroy(self, handle: ServerHandle) -> None:
        self.stopped.append(handle.server_id)


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


class _CorruptReadStorage(FakeStorage):
    async def read(self, path: str) -> bytes:
        data = self._store.get(path, b"")
        return data[:-1] if data else b""


@pytest.mark.usefixtures("init_test_db")
class TestRestartSaga:
    @pytest.mark.asyncio
    async def test_restart_saga_success(self) -> None:
        orchestrator = SagaOrchestrator()
        provider = FakeProvider()
        saga = RestartSaga(orchestrator)

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = Server.create(
                server_id=ServerId("saga-restart-1"),
                name="SagaRestart",
                server_type=ServerType.VANILLA,
                minecraft_version=MinecraftVersion.parse("1.21"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments(),
                properties=ServerProperties(port=PortNumber(25565)),
            )
            server.start()
            server.mark_running(pid=100, port=25565)
            server.collect_events()
            await repo.save(server)
            await session.commit()

        await saga.execute(server, provider)
        assert len(provider.stopped) > 0

    @pytest.mark.asyncio
    async def test_restart_saga_compensates_on_failure(self) -> None:
        orchestrator = SagaOrchestrator()
        provider = FakeProvider()
        provider.status_result = ServerRuntimeStatus.ERROR
        saga = RestartSaga(orchestrator)

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = Server.create(
                server_id=ServerId("saga-restart-fail"),
                name="SagaRestartFail",
                server_type=ServerType.VANILLA,
                minecraft_version=MinecraftVersion.parse("1.21"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments(),
                properties=ServerProperties(port=PortNumber(25565)),
            )
            server.start()
            server.mark_running(pid=200, port=25565)
            server.collect_events()
            await repo.save(server)
            await session.commit()

        await saga.execute(server, provider)
        assert len(provider.stopped) > 0


@pytest.mark.usefixtures("init_test_db")
class TestDeploymentSaga:
    @pytest.mark.asyncio
    async def test_deployment_saga(self) -> None:
        orchestrator = SagaOrchestrator()
        provider = FakeProvider()
        saga = DeploymentSaga(orchestrator)

        await saga.execute(ServerId("saga-dep-1"), provider, {})

        assert "saga-dep-1" in provider.started


class TestDeploymentOrchestrator:
    def test_get_provider(self) -> None:
        from app.modules.server.infrastructure.providers import provider_factory

        orchestrator = DeploymentOrchestrator(provider_factory)
        provider = orchestrator.get_provider("docker")

        assert provider is not None
        assert provider.provider_type == "docker"
        with pytest.raises(ValueError):
            orchestrator.get_provider("local")


@pytest.mark.usefixtures("init_test_db")
class TestBackupSaga:
    async def _seed_server(self, server_id: ServerId, server_dir: str) -> None:
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
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

    def _seed_world(self, server_dir: str) -> None:
        world_dir = os.path.join(server_dir, "world", "region")
        os.makedirs(world_dir, exist_ok=True)
        with open(os.path.join(world_dir, "r.0.0.mca"), "wb") as f:
            f.write(b"\x00" * 1024)
        with open(os.path.join(server_dir, "server.properties"), "w", encoding="utf-8") as f:
            f.write("motd=saga test\n")

    @pytest.mark.asyncio
    async def test_backup_saga_full_flow(self, tmp_path) -> None:
        orchestrator = SagaOrchestrator()
        storage = FakeStorage()
        saga = BackupSaga(orchestrator)

        backup_id = BackupJobId("saga-bak-1")
        server_id = ServerId("srv-1")

        server_dir = str(tmp_path / "server")
        self._seed_world(server_dir)
        await self._seed_server(server_id, server_dir)

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = BackupJob.create(backup_id=backup_id, server_id=server_id)
            await repo.save_job(job)
            await session.commit()

        await saga.execute(
            backup_id,
            server_id,
            storage,
            encryption=BackupEncryption(key=os.urandom(32)),
        )

        path = f"{backup_id}.tar.gz.enc"
        assert await storage.exists(path) is True
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            loaded = await repo.get_job(backup_id)
            assert loaded.status.value == "completed"
            assert loaded.storage_path == path

    @pytest.mark.asyncio
    async def test_backup_saga_compensates_on_verify_fail(self, tmp_path) -> None:
        orchestrator = SagaOrchestrator()
        storage = _CorruptReadStorage()
        saga = BackupSaga(orchestrator)

        backup_id = BackupJobId("saga-bak-fail")
        server_id = ServerId("srv-1")

        server_dir = str(tmp_path / "server")
        self._seed_world(server_dir)
        await self._seed_server(server_id, server_dir)

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = BackupJob.create(backup_id=backup_id, server_id=server_id)
            await repo.save_job(job)
            await session.commit()

        await saga.execute(
            backup_id,
            server_id,
            storage,
            encryption=BackupEncryption(key=os.urandom(32)),
        )

        path = f"{backup_id}.tar.gz.enc"
        assert await storage.exists(path) is False
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            loaded = await repo.get_job(backup_id)
            assert loaded.status.value == "failed"
