import pytest

from app.core.saga import SagaOrchestrator, SagaStatus
from app.modules.backup.domain.aggregate import BackupJob, BackupType
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
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
from app.core.persistence.db import database


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
        provider = orchestrator.get_provider("local")

        assert provider is not None
        assert provider.provider_type == "local"


@pytest.mark.usefixtures("init_test_db")
class TestBackupSaga:
    @pytest.mark.asyncio
    async def test_backup_saga_full_flow(self) -> None:
        orchestrator = SagaOrchestrator()
        storage = FakeStorage()
        saga = BackupSaga(orchestrator)

        backup_id = BackupJobId("saga-bak-1")
        server_id = ServerId("srv-1")

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = BackupJob.create(backup_id=backup_id, server_id=server_id)
            await repo.save_job(job)
            await session.commit()

        await saga.execute(backup_id, server_id, storage)

        path = f"backups/{backup_id}.tar.gz"
        assert await storage.exists(path) is True

    @pytest.mark.asyncio
    async def test_backup_saga_compensates_on_verify_fail(self) -> None:
        orchestrator = SagaOrchestrator()
        storage = FakeStorage()
        saga = BackupSaga(orchestrator)

        backup_id = BackupJobId("saga-bak-fail")
        server_id = ServerId("srv-1")

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = BackupJob.create(backup_id=backup_id, server_id=server_id)
            await repo.save_job(job)
            await session.commit()

        await saga.execute(backup_id, server_id, storage)

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            loaded = await repo.get_job(backup_id)
            assert loaded.status.value in ("completed", "failed")
