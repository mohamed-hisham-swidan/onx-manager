import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.exceptions import ServerNotFoundError
from app.modules.server.application.commands.create_server import (
    CreateServerCommand,
    CreateServerHandler,
)
from app.modules.server.application.commands.delete_server import (
    DeleteServerCommand,
    DeleteServerHandler,
)
from app.modules.server.application.commands.import_server import (
    ImportServerCommand,
    ImportServerHandler,
)
from app.modules.server.application.commands.restart_server import (
    RestartServerCommand,
    RestartServerHandler,
)
from app.modules.server.application.commands.start_server import (
    StartServerCommand,
    StartServerHandler,
)
from app.modules.server.application.commands.stop_server import (
    StopServerCommand,
    StopServerHandler,
)
from app.modules.server.application.commands.update_server_config import (
    UpdateServerConfigCommand,
    UpdateServerConfigHandler,
)
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
from app.modules.shared.value_objects import MinecraftVersion, ServerId
from app.core.persistence.db import database


def _mock_provisioning():
    return patch(
        "app.modules.server.application.services.jar_service.download_server_jar",
        AsyncMock(return_value="/tmp/mock-jar/server.jar"),
    )


async def _create_test_server(
    server_id: str,
    name: str = "TestServer",
    make_running: bool = False,
    with_deployment: bool = False,
) -> Server:
    deployment = None
    if with_deployment:
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path=f"/tmp/mcs-test/{server_id}",
            working_directory=".",
            startup_jar="server.jar",
        )
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        server = Server.create(
            server_id=ServerId(server_id),
            name=name,
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            deployment=deployment,
        )
        if make_running:
            server.start()
            server.mark_running(pid=100, port=25565)
        server.collect_events()
        await repo.save(server)
        await session.commit()
        return server


async def _get_server(server_id: str) -> Server:
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        return await repo.get(ServerId(server_id))


def _bus(event_bus: EventBus) -> CommandBus:
    return CommandBus()


@pytest.mark.usefixtures("init_test_db")
class TestCreateServerHandler:
    @pytest.mark.asyncio
    async def test_create_server_success(self, event_bus: EventBus) -> None:
        with _mock_provisioning():
            handler = CreateServerHandler(event_bus)
            cmd = CreateServerCommand(
                name="Test Server",
                minecraft_version="1.21.4",
                min_memory_mb=1024,
                max_memory_mb=2048,
                port=25565,
                gamemode="survival",
                difficulty="easy",
            )

            result = await handler.handle(cmd)

            assert result.success is True
            assert "server_id" in result.data

            server = await _get_server(result.data["server_id"])
            assert server.name == "Test Server"
            assert str(server.minecraft_version) == "1.21.4"

    @pytest.mark.asyncio
    async def test_create_server_invalid_version(self, event_bus: EventBus) -> None:
        bus = _bus(event_bus)
        bus.register(CreateServerCommand, CreateServerHandler(event_bus))
        cmd = CreateServerCommand(name="Bad Server", minecraft_version="invalid")

        result = await bus.send(cmd)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_create_server_through_bus(self, event_bus: EventBus) -> None:
        with _mock_provisioning():
            bus = _bus(event_bus)
            bus.register(CreateServerCommand, CreateServerHandler(event_bus))
            cmd = CreateServerCommand(name="Bus Server", minecraft_version="1.20.4")

            result = await bus.send(cmd)

            assert result.success is True
            assert "server_id" in result.data


@pytest.mark.usefixtures("init_test_db")
class TestDeleteServerHandler:
    @pytest.mark.asyncio
    async def test_delete_existing_server(self, event_bus: EventBus) -> None:
        await _create_test_server("test-del-1")

        handler = DeleteServerHandler(event_bus)
        result = await handler.handle(DeleteServerCommand(server_id="test-del-1"))

        assert result.success is True
        assert result.data["server_id"] == "test-del-1"

        with pytest.raises(ServerNotFoundError):
            await _get_server("test-del-1")

    @pytest.mark.asyncio
    async def test_delete_nonexistent_server_idempotent(self, event_bus: EventBus) -> None:
        bus = _bus(event_bus)
        bus.register(DeleteServerCommand, DeleteServerHandler(event_bus))
        result = await bus.send(DeleteServerCommand(server_id="nonexistent"))

        assert result.success is False
        assert result.error_code == "NOT_FOUND"


@pytest.mark.usefixtures("init_test_db")
class TestStartServerHandler:
    @pytest.mark.asyncio
    async def test_start_created_server_rejected(self, event_bus: EventBus) -> None:
        await _create_test_server("test-start-1")

        handler = StartServerHandler(event_bus)
        result = await handler.handle(StartServerCommand(server_id="test-start-1"))

        assert result.success is False
        assert result.error_code == "NO_DEPLOYMENT"

        loaded = await _get_server("test-start-1")
        assert loaded.status.value == "created"

    @pytest.mark.asyncio
    async def test_start_nonexistent_server(self, event_bus: EventBus) -> None:
        bus = _bus(event_bus)
        bus.register(StartServerCommand, StartServerHandler(event_bus))
        result = await bus.send(StartServerCommand(server_id="nonexistent"))

        assert result.success is False

    @pytest.mark.asyncio
    async def test_start_server_with_deployment(self, event_bus: EventBus) -> None:
        await _create_test_server("test-start-deploy-1", with_deployment=True)

        from app.modules.server.infrastructure.providers.base import (
            DeploymentResult,
            ServerRuntimeStatus,
        )
        mock_provider = AsyncMock()
        mock_provider.provider_type = "local"
        mock_provider.start.return_value = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=12345,
            metadata={"session_name": "mcs-test-start-deploy-1"},
        )

        handler = StartServerHandler(event_bus)
        with patch("app.modules.server.application.commands.start_server.provider_factory.get", return_value=mock_provider):
            result = await handler.handle(StartServerCommand(server_id="test-start-deploy-1"))

        assert result.success is True
        loaded = await _get_server("test-start-deploy-1")
        assert loaded.status.value in ("running", "starting")

    @pytest.mark.asyncio
    async def test_start_server_deployment_sets_runtime(self, event_bus: EventBus) -> None:
        await _create_test_server("test-start-runtime-1", with_deployment=True)

        from app.modules.server.infrastructure.providers.base import (
            DeploymentResult,
            ServerRuntimeStatus,
        )
        mock_provider = AsyncMock()
        mock_provider.provider_type = "local"
        mock_provider.start.return_value = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=12345,
            metadata={"session_name": "mcs-test-start-runtime-1"},
        )

        handler = StartServerHandler(event_bus)
        with patch("app.modules.server.application.commands.start_server.provider_factory.get", return_value=mock_provider):
            result = await handler.handle(StartServerCommand(server_id="test-start-runtime-1"))

        assert result.success is True
        loaded = await _get_server("test-start-runtime-1")
        if loaded.status.value == "running":
            assert loaded.runtime.pid is not None
            assert loaded.runtime.port is not None

    @pytest.mark.asyncio
    async def test_start_applies_pending_plugin_deletions(self, event_bus: EventBus) -> None:
        await _create_test_server("test-start-pdel-1", with_deployment=True)

        from app.modules.server.infrastructure.providers.base import (
            DeploymentResult,
            ServerRuntimeStatus,
        )
        mock_provider = AsyncMock()
        mock_provider.provider_type = "local"
        mock_provider.start.return_value = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=12345,
            metadata={"session_name": "mcs-test-start-pdel-1"},
        )

        mock_consume = AsyncMock(return_value=[])
        handler = StartServerHandler(event_bus)
        with (
            patch("app.modules.server.application.commands.start_server.provider_factory.get", return_value=mock_provider),
            patch(
                "app.modules.server.application.commands.start_server.consume_pending_plugin_deletions",
                mock_consume,
            ),
        ):
            result = await handler.handle(StartServerCommand(server_id="test-start-pdel-1"))

        assert result.success is True
        mock_consume.assert_awaited_once()
        args, _kwargs = mock_consume.await_args
        assert args[0] == "test-start-pdel-1"
        assert args[1].endswith("test-start-pdel-1")


@pytest.mark.usefixtures("init_test_db")
class TestStopServerHandler:
    @pytest.mark.asyncio
    async def test_stop_running_server(self, event_bus: EventBus) -> None:
        await _create_test_server("test-stop-1", make_running=True)

        handler = StopServerHandler(event_bus)
        result = await handler.handle(StopServerCommand(server_id="test-stop-1", reason="test"))

        assert result.success is True

        loaded = await _get_server("test-stop-1")
        assert loaded.status.value == "stopped"
        assert loaded.runtime.external_id == ""


@pytest.mark.usefixtures("init_test_db")
class TestRestartServerHandler:
    @pytest.mark.asyncio
    async def test_restart_server_no_deployment(self, event_bus: EventBus) -> None:
        await _create_test_server("test-restart-1", make_running=True)

        handler = RestartServerHandler(event_bus)
        result = await handler.handle(RestartServerCommand(server_id="test-restart-1"))

        assert result.success is False
        assert result.error_code == "NO_DEPLOYMENT"

    @pytest.mark.asyncio
    async def test_restart_server_with_deployment(self, event_bus: EventBus) -> None:
        await _create_test_server("test-restart-deploy-1", make_running=True, with_deployment=True)

        from app.modules.server.infrastructure.providers.base import (
            DeploymentResult,
            ServerRuntimeStatus,
        )
        mock_provider = AsyncMock()
        mock_provider.provider_type = "local"
        mock_provider.status.return_value = ServerRuntimeStatus.STOPPED
        mock_provider.start.return_value = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=12345,
            metadata={"session_name": "mcs-test-restart-deploy-1"},
        )

        handler = RestartServerHandler(event_bus)
        with patch("app.modules.server.application.commands.restart_server.provider_factory.get", return_value=mock_provider):
            result = await handler.handle(RestartServerCommand(server_id="test-restart-deploy-1"))

        assert result.success is True
        loaded = await _get_server("test-restart-deploy-1")
        assert loaded.status.value in ("running", "starting")

    @pytest.mark.asyncio
    async def test_restart_applies_pending_plugin_deletions(self, event_bus: EventBus) -> None:
        await _create_test_server("test-restart-pdel-1", make_running=True, with_deployment=True)

        from app.modules.server.infrastructure.providers.base import (
            DeploymentResult,
            ServerRuntimeStatus,
        )
        mock_provider = AsyncMock()
        mock_provider.provider_type = "local"
        mock_provider.status.return_value = ServerRuntimeStatus.STOPPED
        mock_provider.start.return_value = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=12345,
            metadata={"session_name": "mcs-test-restart-pdel-1"},
        )

        mock_consume = AsyncMock(return_value=[])
        handler = RestartServerHandler(event_bus)
        with (
            patch("app.modules.server.application.commands.restart_server.provider_factory.get", return_value=mock_provider),
            patch(
                "app.modules.server.application.commands.restart_server.consume_pending_plugin_deletions",
                mock_consume,
            ),
        ):
            result = await handler.handle(RestartServerCommand(server_id="test-restart-pdel-1"))

        assert result.success is True
        mock_consume.assert_awaited_once()
        args, _kwargs = mock_consume.await_args
        assert args[0] == "test-restart-pdel-1"
        assert args[1].endswith("test-restart-pdel-1")


@pytest.mark.usefixtures("init_test_db")
class TestUpdateServerConfigHandler:
    @pytest.mark.asyncio
    async def test_update_properties(self, event_bus: EventBus) -> None:
        await _create_test_server("test-upd-1")

        handler = UpdateServerConfigHandler(event_bus)
        result = await handler.handle(UpdateServerConfigCommand(
            server_id="test-upd-1",
            properties={"motd": "Updated MOTD", "max_players": 50},
            min_memory_mb=2048,
            max_memory_mb=4096,
        ))

        assert result.success is True

        loaded = await _get_server("test-upd-1")
        assert loaded.properties.motd == "Updated MOTD"
        assert loaded.properties.max_players == 50
        assert loaded.memory.min_mb == 2048
        assert loaded.memory.max_mb == 4096

    @pytest.mark.asyncio
    async def test_update_nonexistent_server(self, event_bus: EventBus) -> None:
        bus = _bus(event_bus)
        bus.register(UpdateServerConfigCommand, UpdateServerConfigHandler(event_bus))
        result = await bus.send(UpdateServerConfigCommand(
            server_id="nonexistent",
            properties={"motd": "test"},
        ))

        assert result.success is False


@patch("app.modules.server.application.commands.delete_server.local_fs.delete_dir")
@pytest.mark.usefixtures("init_test_db")
class TestDeleteServerFS:
    @pytest.mark.asyncio
    async def test_delete_removes_directory(self, mock_delete_dir: AsyncMock, event_bus: EventBus) -> None:
        await _create_test_server("test-del-fs-1", with_deployment=True)

        handler = DeleteServerHandler(event_bus)
        result = await handler.handle(DeleteServerCommand(server_id="test-del-fs-1"))

        assert result.success is True
        mock_delete_dir.assert_called_once()
        call_arg = mock_delete_dir.call_args[0][0]
        assert "test-del-fs-1" in call_arg

    @pytest.mark.asyncio
    async def test_double_delete_idempotent(self, mock_delete_dir: AsyncMock, event_bus: EventBus) -> None:
        await _create_test_server("test-del-double-1", with_deployment=True)

        handler = DeleteServerHandler(event_bus)
        r1 = await handler.handle(DeleteServerCommand(server_id="test-del-double-1"))
        assert r1.success is True

        r2 = await handler.handle(DeleteServerCommand(server_id="test-del-double-1"))
        assert r2.success is False
        assert r2.error_code == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_delete_without_deployment_skips_fs(self, mock_delete_dir: AsyncMock, event_bus: EventBus) -> None:
        await _create_test_server("test-del-nodeploy-1", with_deployment=False)

        handler = DeleteServerHandler(event_bus)
        result = await handler.handle(DeleteServerCommand(server_id="test-del-nodeploy-1"))

        assert result.success is True
        mock_delete_dir.assert_not_called()


@pytest.mark.usefixtures("init_test_db")
class TestImportServerHandler:
    @pytest.mark.asyncio
    async def test_import_cleans_up_on_rollback(self, event_bus: EventBus) -> None:
        with (
            tempfile.TemporaryDirectory() as src_dir,
            tempfile.TemporaryDirectory() as servers_root,
        ):
            os.makedirs(os.path.join(src_dir, "world"), exist_ok=True)
            with open(os.path.join(src_dir, "server.jar"), "wb") as f:
                f.write(b"fake jar")

            with (
                patch("app.modules.server.application.commands.import_server.SERVERS_DATA_DIR", servers_root),
                patch("app.modules.server.application.commands.import_server.local_fs.delete_dir") as mock_delete,
                patch("app.modules.server.infrastructure.repository.SQLServerRepository.save",
                      side_effect=Exception("DB save failed")),
            ):
                handler = ImportServerHandler(event_bus)
                with pytest.raises(Exception, match="DB save failed"):
                    await handler.handle(ImportServerCommand(
                        source_path=src_dir,
                        name="ImportFailTest",
                        minecraft_version="1.21",
                        server_type="vanilla",
                    ))

            assert mock_delete.called, "delete_dir should be called to clean up on rollback"

    @pytest.mark.asyncio
    async def test_import_success_does_not_cleanup(self, event_bus: EventBus) -> None:
        with (
            tempfile.TemporaryDirectory() as src_dir,
            tempfile.TemporaryDirectory() as servers_root,
        ):
            os.makedirs(os.path.join(src_dir, "world"), exist_ok=True)
            with open(os.path.join(src_dir, "server.jar"), "wb") as f:
                f.write(b"fake jar")

            with (
                patch("app.modules.server.application.commands.import_server.SERVERS_DATA_DIR", servers_root),
                patch("app.modules.server.application.commands.import_server.local_fs.delete_dir") as mock_delete,
            ):
                handler = ImportServerHandler(event_bus)
                result = await handler.handle(ImportServerCommand(
                    source_path=src_dir,
                    name="ImportSuccessTest",
                    minecraft_version="1.21",
                    server_type="vanilla",
                ))

            assert result.success is True
            mock_delete.assert_not_called()


@pytest.mark.usefixtures("init_test_db")
class TestUpdateServerConfigHandler:
    @pytest.mark.asyncio
    async def test_update_name_updates_db_and_properties_file(self, event_bus: EventBus, tmp_path) -> None:
        props_file = tmp_path / "server.properties"
        props_file.write_text("#Minecraft server properties\nserver-name=OldName\nmotd=Initial\n", encoding="utf-8")

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            deployment = ServerDeployment(
                location_type=LocationType.LOCAL,
                root_path=str(tmp_path),
                working_directory=".",
                startup_jar="server.jar",
            )
            server = Server.create(
                server_id=ServerId("test-upd-name"),
                name="OldName",
                server_type=ServerType.VANILLA,
                minecraft_version=MinecraftVersion.parse("1.21"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments(),
                properties=ServerProperties(port=PortNumber(25565)),
                deployment=deployment,
            )
            await repo.save(server)
            await session.commit()

        handler = UpdateServerConfigHandler(event_bus)
        result = await handler.handle(UpdateServerConfigCommand(
            server_id="test-upd-name",
            name="NewRenamedServer",
            properties={"motd": "Updated MOTD", "max_players": 40},
        ))

        assert result.success is True
        loaded = await _get_server("test-upd-name")
        assert loaded.name == "NewRenamedServer"
        assert loaded.properties.motd == "Updated MOTD"
        assert loaded.properties.max_players == 40

        content = props_file.read_text(encoding="utf-8")
        assert "server-name=NewRenamedServer" in content
        assert "motd=Updated MOTD" in content
        assert "max-players=40" in content

