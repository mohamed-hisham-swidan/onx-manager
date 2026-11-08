import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.health.infrastructure.models  # noqa: F401
from app.core.command_bus import CommandBus, CommandResult
from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.exceptions import ServerNotFoundError
from app.core.persistence.db import database
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
from app.modules.server.application.commands.retry_provisioning import (
    RetryProvisioningCommand,
    RetryProvisioningHandler,
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
from app.modules.server.application.queries.get_server_console import (
    GetServerConsoleHandler,
    GetServerConsoleQuery,
)
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
from app.modules.shared.value_objects import MinecraftVersion, ServerId


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
    root_path: str | None = None,
) -> Server:
    deployment = None
    if with_deployment:
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path=root_path or os.path.join(AppSettings().servers_data_dir, server_id),
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
            server.mark_running(pid=100, port=25565, external_id=f"ext-{server_id}")
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


@pytest.fixture(autouse=True)
def _mock_runtime_supervisor_in_command_tests():
    with (
        patch(
            "app.modules.server.application.commands.start_server.RuntimeSupervisor.start_for"
        ) as m1,
        patch(
            "app.modules.server.application.commands.restart_server.RuntimeSupervisor.start_for"
        ) as m2,
        patch(
            "app.modules.server.application.commands.start_server._port_is_listening",
            return_value=False,
        ),
        patch(
            "app.modules.server.application.commands.stop_server._port_is_listening",
            return_value=False,
        ),
        patch(
            "app.modules.server.application.commands.stop_server._wait_for_port_free",
            AsyncMock(return_value=True),
        ),
        patch(
            "app.modules.server.application.commands.restart_server._port_is_listening",
            return_value=False,
        ),
        patch(
            "app.modules.server.application.commands.restart_server._wait_for_port_free",
            AsyncMock(return_value=True),
        ),
    ):
        yield m1, m2


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

    @pytest.mark.asyncio
    async def test_delete_server_confirms_not_running_before_calling_destroy(
        self, event_bus: EventBus
    ) -> None:
        from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus

        await _create_test_server("test-del-f6-running", make_running=True)

        mock_provider = AsyncMock()
        mock_provider.name = "local"
        mock_provider.status.return_value = ServerRuntimeStatus.RUNNING

        handler = DeleteServerHandler(
            event_bus, provider_factory=MagicMock(get=lambda _: mock_provider)
        )

        stop_target = (
            "app.modules.server.application.commands.delete_server.StopServerHandler.handle"
        )
        port_target = (
            "app.modules.server.application.commands.delete_server._port_is_listening"
        )
        with (
            patch(stop_target) as mock_stop,
            patch(port_target, return_value=False),
        ):
            mock_stop.return_value = CommandResult(success=True)
            result = await handler.handle(DeleteServerCommand(server_id="test-del-f6-running"))

        assert result.success is False
        assert result.error_code == "DELETE_STOP_NOT_CONFIRMED"
        assert "runtime process/container could not be stopped" in (result.error or "")
        mock_provider.destroy.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_server_aborts_if_port_still_listening(
        self, event_bus: EventBus
    ) -> None:
        from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus

        await _create_test_server("test-del-f6-port", make_running=True)

        mock_provider = AsyncMock()
        mock_provider.name = "local"
        mock_provider.status.return_value = ServerRuntimeStatus.STOPPED

        handler = DeleteServerHandler(
            event_bus, provider_factory=MagicMock(get=lambda _: mock_provider)
        )

        stop_target = (
            "app.modules.server.application.commands.delete_server.StopServerHandler.handle"
        )
        port_target = (
            "app.modules.server.application.commands.delete_server._port_is_listening"
        )
        with (
            patch(stop_target) as mock_stop,
            patch(port_target, return_value=True),
        ):
            mock_stop.return_value = CommandResult(success=True)
            result = await handler.handle(DeleteServerCommand(server_id="test-del-f6-port"))

        assert result.success is False
        assert result.error_code == "DELETE_STOP_NOT_CONFIRMED"
        assert "still occupied" in (result.error or "")
        mock_provider.destroy.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_server_provider_factory_failure_returns_error_result(
        self, event_bus: EventBus
    ) -> None:
        await _create_test_server("test-del-f6-factory", make_running=True)

        bad_factory = MagicMock()
        bad_factory.get.side_effect = RuntimeError("Provider plugin crashed")

        handler = DeleteServerHandler(event_bus, provider_factory=bad_factory)
        result = await handler.handle(DeleteServerCommand(server_id="test-del-f6-factory"))

        assert result.success is False
        assert result.error_code == "PROVIDER_UNAVAILABLE"
        assert "Provider plugin crashed" in (result.error or "")



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
            metadata={"session_name": "onx-test-start-deploy-1"},
        )

        handler = StartServerHandler(event_bus)
        with patch(
            "app.modules.server.application.commands.start_server.provider_factory.get",
            return_value=mock_provider,
        ):
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
            metadata={"session_name": "onx-test-start-runtime-1"},
        )

        handler = StartServerHandler(event_bus)
        with patch(
            "app.modules.server.application.commands.start_server.provider_factory.get",
            return_value=mock_provider,
        ):
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
            metadata={"session_name": "onx-test-start-pdel-1"},
        )

        mock_consume = AsyncMock(return_value=[])
        handler = StartServerHandler(event_bus)
        with (
            patch(
                "app.modules.server.application.commands.start_server.provider_factory.get",
                return_value=mock_provider,
            ),
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

    @pytest.mark.asyncio
    async def test_start_server_prepares_environment_before_start(
        self, event_bus: EventBus
    ) -> None:
        await _create_test_server("test-start-prep-1", with_deployment=True)

        from app.modules.server.infrastructure.providers.base import (
            DeploymentResult,
            ServerRuntimeStatus,
        )

        mock_provider = AsyncMock()
        mock_provider.provider_type = "docker"
        mock_provider.start.return_value = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=12345,
            metadata={"session_name": "onx-test-start-prep-1"},
        )

        handler = StartServerHandler(event_bus)
        with patch(
            "app.modules.server.application.commands.start_server.provider_factory.get",
            return_value=mock_provider,
        ):
            result = await handler.handle(StartServerCommand(server_id="test-start-prep-1"))

        assert result.success is True
        mock_provider.prepare_environment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_server_timeout_marks_stopped_and_returns_details(
        self, event_bus: EventBus
    ) -> None:
        await _create_test_server("test-start-tout-1", with_deployment=True)

        mock_provider = AsyncMock()
        mock_provider.provider_type = "docker"

        handler = StartServerHandler(event_bus)
        with (
            patch(
                "app.modules.server.application.commands.start_server.provider_factory.get",
                return_value=mock_provider,
            ),
            patch("asyncio.wait_for", AsyncMock(side_effect=TimeoutError())),
        ):
            result = await handler.handle(StartServerCommand(server_id="test-start-tout-1"))

        assert result.success is False
        assert result.error_code == "STARTUP_TIMEOUT"
        assert result.details["timeout_seconds"] == 30
        assert result.details["provider"] == "local"
        loaded = await _get_server("test-start-tout-1")
        assert loaded.status.value == "stopped"

    @pytest.mark.asyncio
    async def test_start_server_idempotent_when_running(self, event_bus: EventBus) -> None:
        from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus

        server = await _create_test_server(
            "test-start-idem-running", make_running=False, with_deployment=True
        )
        server.start()
        server.mark_running(pid=1234, port=25565, external_id="onx-test-start-idem-running")
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        mock_provider = AsyncMock()
        mock_provider.name = "local"
        mock_provider.status.return_value = ServerRuntimeStatus.RUNNING

        handler = StartServerHandler(event_bus, provider=mock_provider)
        result = await handler.handle(StartServerCommand(server_id="test-start-idem-running"))

        assert result.success is True
        assert result.data["idempotent"] is True
        assert result.data["status"] == "running"
        mock_provider.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_server_idempotent_when_starting_and_alive(
        self, event_bus: EventBus
    ) -> None:
        from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus

        server = await _create_test_server(
            "test-start-idem-starting", make_running=False, with_deployment=True
        )
        server.start()
        server.record_runtime_starting(
            pid=2345, port=25565, external_id="onx-test-start-idem-starting"
        )
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        mock_provider = AsyncMock()
        mock_provider.name = "local"
        mock_provider.status.return_value = ServerRuntimeStatus.RUNNING

        handler = StartServerHandler(event_bus, provider=mock_provider)
        result = await handler.handle(StartServerCommand(server_id="test-start-idem-starting"))

        assert result.success is True
        assert result.data["idempotent"] is True
        assert result.data["status"] == "starting"
        mock_provider.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_server_fails_closed_when_port_occupied(self, event_bus: EventBus) -> None:
        await _create_test_server("test-start-port-occ", with_deployment=True)

        mock_provider = AsyncMock()
        handler = StartServerHandler(event_bus, provider=mock_provider)

        target = "app.modules.server.application.commands.start_server._port_is_listening"
        with patch(target, return_value=True):
            result = await handler.handle(StartServerCommand(server_id="test-start-port-occ"))

        assert result.success is False
        assert result.error_code == "PORT_OCCUPIED"
        assert "still occupied" in (result.error or "")

        loaded = await _get_server("test-start-port-occ")
        assert loaded.status == ServerStatus.STOPPED
        mock_provider.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_server_refuses_busy_states(self, event_bus: EventBus) -> None:
        server = await _create_test_server("test-start-busy", with_deployment=True)
        handler = StartServerHandler(event_bus)

        busy_states = (
            ServerStatus.PROVISIONING,
            ServerStatus.RESTORING,
            ServerStatus.STOPPING,
        )
        for busy_status in busy_states:
            server._status = busy_status
            async with database.session_factory() as session:
                repo = SQLServerRepository(session)
                await repo.save(server)
                await session.commit()

            result = await handler.handle(StartServerCommand(server_id="test-start-busy"))
            assert result.success is False
            assert result.error_code == "SERVER_BUSY"

    @pytest.mark.asyncio
    async def test_start_server_refuses_invalid_states(self, event_bus: EventBus) -> None:
        server = await _create_test_server("test-start-invalid", with_deployment=True)
        handler = StartServerHandler(event_bus)

        for invalid_status in (ServerStatus.PROVISIONING_FAILED, ServerStatus.BROKEN):
            server._status = invalid_status
            async with database.session_factory() as session:
                repo = SQLServerRepository(session)
                await repo.save(server)
                await session.commit()

            result = await handler.handle(StartServerCommand(server_id="test-start-invalid"))
            assert result.success is False
            assert result.error_code == "INVALID_SERVER_STATE"

    @pytest.mark.asyncio
    async def test_start_server_timeout_cleans_up_runtime_and_crashes_if_alive(
        self, event_bus: EventBus
    ) -> None:
        from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus

        await _create_test_server("test-start-tout-cleanup", with_deployment=True)

        mock_provider = AsyncMock()
        mock_provider.name = "docker"
        mock_provider.provider_type = "docker"
        mock_provider.start.side_effect = TimeoutError()
        # Pretend runtime is still running after forced stop
        mock_provider.status.return_value = ServerRuntimeStatus.RUNNING

        handler = StartServerHandler(event_bus, provider=mock_provider)
        with (
            patch(
                "app.modules.server.application.commands.start_server.provider_factory.get",
                return_value=mock_provider,
            ),
            patch("asyncio.wait_for", AsyncMock(side_effect=TimeoutError())),
        ):
            result = await handler.handle(StartServerCommand(server_id="test-start-tout-cleanup"))

        assert result.success is False
        assert result.error_code == "STARTUP_TIMEOUT"
        mock_provider.stop.assert_awaited_once()
        mock_provider.destroy.assert_awaited_once()

        loaded = await _get_server("test-start-tout-cleanup")
        assert loaded.status == ServerStatus.CRASHED



@pytest.mark.usefixtures("init_test_db")
class TestStopServerHandler:
    @pytest.fixture(autouse=True)
    def _mock_default_stop_provider(self):
        from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus

        mock_p = AsyncMock()
        mock_p.provider_type = "local"
        mock_p.stop.return_value = None
        mock_p.status.return_value = ServerRuntimeStatus.STOPPED
        with patch(
            "app.modules.server.application.commands.stop_server.provider_factory.get",
            return_value=mock_p,
        ):
            yield mock_p

    @pytest.mark.asyncio
    async def test_stop_running_server(self, event_bus: EventBus) -> None:
        await _create_test_server("test-stop-1", make_running=True)

        handler = StopServerHandler(event_bus)
        result = await handler.handle(StopServerCommand(server_id="test-stop-1", reason="test"))

        assert result.success is True

        loaded = await _get_server("test-stop-1")
        assert loaded.status.value == "stopped"
        assert loaded.runtime.external_id == ""

    @pytest.mark.asyncio
    async def test_stop_server_unexpected_runtime_status_logged(
        self, event_bus: EventBus, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus

        server = await _create_test_server(
            "test-stop-unexpected", make_running=False, with_deployment=True
        )
        server.start()
        server.mark_running(pid=100, port=25565, external_id="ext-test-unexpected")
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        mock_provider = AsyncMock()
        mock_provider.status.return_value = ServerRuntimeStatus.ERROR
        mock_provider.stop.return_value = None

        handler = StopServerHandler(event_bus)
        with (
            caplog.at_level(logging.WARNING),
            patch(
                "app.modules.server.application.commands.stop_server.provider_factory.get",
                return_value=mock_provider,
            ),
        ):
            result = await handler.handle(
                StopServerCommand(server_id="test-stop-unexpected", reason="test")
            )

        assert result.success is False
        assert result.error_code == "SERVER_STOP_UNCONFIRMED"


@pytest.mark.usefixtures("init_test_db")
class TestRestartServerHandler:
    @pytest.mark.asyncio
    async def test_restart_server_no_deployment(self, event_bus: EventBus) -> None:
        await _create_test_server("test-restart-1", make_running=True)

        from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus

        mock_provider = AsyncMock()
        mock_provider.provider_type = "local"
        mock_provider.status.return_value = ServerRuntimeStatus.STOPPED

        handler = RestartServerHandler(event_bus)
        with patch(
            "app.modules.server.application.commands.restart_server.provider_factory.get",
            return_value=mock_provider,
        ):
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
            metadata={"session_name": "onx-test-restart-deploy-1"},
        )

        handler = RestartServerHandler(event_bus)
        with patch(
            "app.modules.server.application.commands.restart_server.provider_factory.get",
            return_value=mock_provider,
        ):
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
            metadata={"session_name": "onx-test-restart-pdel-1"},
        )

        mock_consume = AsyncMock(return_value=[])
        handler = RestartServerHandler(event_bus)
        with (
            patch(
                "app.modules.server.application.commands.restart_server.provider_factory.get",
                return_value=mock_provider,
            ),
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

    @pytest.mark.asyncio
    async def test_restart_server_timeout_marks_stopped_and_returns_details(
        self, event_bus: EventBus
    ) -> None:
        await _create_test_server("test-restart-tout-1", make_running=True, with_deployment=True)

        from app.modules.server.infrastructure.providers.base import ServerRuntimeStatus

        mock_provider = AsyncMock()
        mock_provider.provider_type = "docker"
        mock_provider.status.return_value = ServerRuntimeStatus.STOPPED

        orig_wait_for = asyncio.wait_for

        async def _fake_wait_for(fut, timeout=None):
            if timeout == 30:
                raise TimeoutError()
            return await orig_wait_for(fut, timeout=timeout)

        handler = RestartServerHandler(event_bus)
        with (
            patch(
                "app.modules.server.application.commands.restart_server.provider_factory.get",
                return_value=mock_provider,
            ),
            patch("asyncio.wait_for", side_effect=_fake_wait_for),
        ):
            result = await handler.handle(RestartServerCommand(server_id="test-restart-tout-1"))

        assert result.success is False
        assert result.error_code == "STARTUP_TIMEOUT"
        assert result.details["timeout_seconds"] == 30
        assert result.details["provider"] == "local"
        loaded = await _get_server("test-restart-tout-1")
        assert loaded.status.value == "stopped"


@pytest.mark.usefixtures("init_test_db")
class TestUpdateServerConfigHandler:
    @pytest.mark.asyncio
    async def test_update_properties(self, event_bus: EventBus) -> None:
        await _create_test_server("test-upd-1")

        handler = UpdateServerConfigHandler(event_bus)
        result = await handler.handle(
            UpdateServerConfigCommand(
                server_id="test-upd-1",
                properties={"motd": "Updated MOTD", "max_players": 50},
                min_memory_mb=2048,
                max_memory_mb=4096,
            )
        )

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
        result = await bus.send(
            UpdateServerConfigCommand(
                server_id="nonexistent",
                properties={"motd": "test"},
            )
        )

        assert result.success is False


@patch("app.modules.server.application.commands.delete_server.local_fs.delete_dir")
@pytest.mark.usefixtures("init_test_db")
class TestDeleteServerFS:
    @pytest.mark.asyncio
    async def test_delete_removes_directory(
        self, mock_delete_dir: AsyncMock, event_bus: EventBus
    ) -> None:
        await _create_test_server("test-del-fs-1", with_deployment=True)

        handler = DeleteServerHandler(event_bus)
        result = await handler.handle(DeleteServerCommand(server_id="test-del-fs-1"))

        assert result.success is True
        mock_delete_dir.assert_called_once()
        call_arg = mock_delete_dir.call_args[0][0]
        assert "test-del-fs-1" in call_arg

    @pytest.mark.asyncio
    async def test_delete_filesystem_failure_returns_error_result(
        self, mock_delete_dir: AsyncMock, event_bus: EventBus
    ) -> None:
        await _create_test_server("test-del-fs-err", with_deployment=True)
        mock_delete_dir.side_effect = PermissionError("Permission denied: .onx/tests")

        handler = DeleteServerHandler(event_bus)
        result = await handler.handle(DeleteServerCommand(server_id="test-del-fs-err"))

        assert result.success is False
        assert result.error_code == "FILESYSTEM_CLEANUP_FAILED"
        assert "filesystem directory could not be removed" in (result.error or "")
        assert result.details is not None
        assert "leftover_path" in result.details
        hint = result.details["cleanup_hint"]
        assert "may be caused by file permissions or active file locks" in hint
        assert "manual_command" not in result.details
        mock_delete_dir.side_effect = None

    @pytest.mark.asyncio
    async def test_double_delete_idempotent(
        self, mock_delete_dir: AsyncMock, event_bus: EventBus
    ) -> None:
        await _create_test_server("test-del-double-1", with_deployment=True)

        handler = DeleteServerHandler(event_bus)
        r1 = await handler.handle(DeleteServerCommand(server_id="test-del-double-1"))
        assert r1.success is True

        r2 = await handler.handle(DeleteServerCommand(server_id="test-del-double-1"))
        assert r2.success is False
        assert r2.error_code == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_delete_refuses_directory_outside_servers_root(
        self, mock_delete_dir: AsyncMock, event_bus: EventBus, tmp_path
    ) -> None:
        outside = tmp_path / "elsewhere" / "srv"
        await _create_test_server(
            "test-del-outside-1", with_deployment=True, root_path=str(outside)
        )

        handler = DeleteServerHandler(event_bus)
        result = await handler.handle(DeleteServerCommand(server_id="test-del-outside-1"))

        assert result.success is False
        assert result.error_code == "FILESYSTEM_CLEANUP_FAILED"
        mock_delete_dir.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_without_deployment_skips_fs(
        self, mock_delete_dir: AsyncMock, event_bus: EventBus
    ) -> None:
        await _create_test_server("test-del-nodeploy-1", with_deployment=False)

        handler = DeleteServerHandler(event_bus)
        result = await handler.handle(DeleteServerCommand(server_id="test-del-nodeploy-1"))

        assert result.success is True
        mock_delete_dir.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_running_server_stops_before_deletion(
        self, mock_delete_dir: AsyncMock, event_bus: EventBus
    ) -> None:
        from unittest.mock import patch

        from app.core.command_bus import CommandResult
        from app.core.persistence.unit_of_work import UnitOfWork

        server = await _create_test_server("test-del-running-1", with_deployment=True)
        # Transition to RUNNING
        server.start()
        async with UnitOfWork(event_bus) as uow:
            repo = SQLServerRepository(uow.session)
            await repo.save(server)
            await uow.commit()

        stop_called = False

        async def fake_stop_handle(_self_cmd: object, _cmd: object) -> CommandResult:
            nonlocal stop_called
            stop_called = True
            return CommandResult(success=True)

        target = "app.modules.server.application.commands.delete_server.StopServerHandler.handle"
        with patch(target, fake_stop_handle):
            handler = DeleteServerHandler(event_bus)
            result = await handler.handle(DeleteServerCommand(server_id="test-del-running-1"))

        assert result.success is True
        assert stop_called is True
        mock_delete_dir.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_docker_server_calls_destroy(
        self, mock_delete_dir: AsyncMock, event_bus: EventBus
    ) -> None:
        from app.modules.server.domain.value_objects import RuntimeInfo

        server = await _create_test_server("test-del-docker-1", with_deployment=True)
        server._runtime = RuntimeInfo(provider="docker", external_id="onx-del-docker-1")
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        mock_provider = AsyncMock()
        mock_provider.destroy = AsyncMock()
        mock_factory = MagicMock()
        mock_factory.get.return_value = mock_provider

        handler = DeleteServerHandler(event_bus, provider_factory=mock_factory)
        result = await handler.handle(DeleteServerCommand(server_id="test-del-docker-1"))

        assert result.success is True
        mock_factory.get.assert_called_once_with("docker")
        mock_provider.destroy.assert_awaited_once()
        handle_arg = mock_provider.destroy.call_args[0][0]
        assert handle_arg.provider == "docker"
        assert handle_arg.server_id == "test-del-docker-1"
        assert handle_arg.external_id == "onx-del-docker-1"
        mock_delete_dir.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_server_destroy_failure_degrades_gracefully(
        self, mock_delete_dir: AsyncMock, event_bus: EventBus
    ) -> None:
        from app.modules.server.domain.value_objects import RuntimeInfo

        server = await _create_test_server("test-del-fail-1", with_deployment=True)
        server._runtime = RuntimeInfo(provider="docker", external_id="onx-del-fail-1")
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        mock_provider = AsyncMock()
        mock_provider.destroy.side_effect = RuntimeError("Docker daemon disconnected")
        mock_factory = MagicMock()
        mock_factory.get.return_value = mock_provider

        handler = DeleteServerHandler(event_bus, provider_factory=mock_factory)
        result = await handler.handle(DeleteServerCommand(server_id="test-del-fail-1"))

        assert result.success is True
        mock_provider.destroy.assert_awaited_once()
        mock_delete_dir.assert_called_once()
        with pytest.raises(ServerNotFoundError):
            await _get_server("test-del-fail-1")

    @pytest.mark.asyncio
    async def test_delete_server_default_provider_destroy_called(
        self, mock_delete_dir: AsyncMock, event_bus: EventBus
    ) -> None:
        from app.modules.server.domain.value_objects import default_provider_for_platform
        from app.modules.server.infrastructure.providers import (
            provider_factory as default_factory,
        )

        await _create_test_server("test-del-default-1", with_deployment=True)
        default_provider = default_factory.get(default_provider_for_platform())

        with patch.object(default_provider, "destroy", AsyncMock()) as mock_destroy:
            handler = DeleteServerHandler(event_bus)
            result = await handler.handle(DeleteServerCommand(server_id="test-del-default-1"))

            assert result.success is True
            mock_destroy.assert_awaited_once()
            handle_arg = mock_destroy.call_args[0][0]
            assert handle_arg.server_id == "test-del-default-1"

    @pytest.mark.asyncio
    async def test_delete_server_corrupted_provider_type_degrades_gracefully(
        self, mock_delete_dir: AsyncMock, event_bus: EventBus
    ) -> None:
        from app.modules.server.domain.value_objects import RuntimeInfo

        server = await _create_test_server("test-del-corrupt-1", with_deployment=True)
        server._runtime = RuntimeInfo(
            provider="bogus_no_such_provider", external_id="onx-del-corrupt"
        )
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        # Uses real default factory (not a mock), verifying factory.get() failure absorption
        handler = DeleteServerHandler(event_bus)
        result = await handler.handle(DeleteServerCommand(server_id="test-del-corrupt-1"))

        assert result.success is True
        mock_delete_dir.assert_called_once()
        with pytest.raises(ServerNotFoundError):
            await _get_server("test-del-corrupt-1")

    @pytest.mark.asyncio
    async def test_delete_server_destroy_timeout_degrades_gracefully(
        self, mock_delete_dir: AsyncMock, event_bus: EventBus
    ) -> None:
        from app.modules.server.domain.value_objects import RuntimeInfo

        server = await _create_test_server("test-del-timeout-1", with_deployment=True)
        server._runtime = RuntimeInfo(provider="docker", external_id="onx-del-timeout-1")
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        async def hanging_destroy(_handle: object) -> None:
            await asyncio.sleep(1.0)

        mock_provider = AsyncMock()
        mock_provider.destroy.side_effect = hanging_destroy
        mock_factory = MagicMock()
        mock_factory.get.return_value = mock_provider

        # Bound timeout to 10ms to verify asyncio.wait_for TimeoutError absorption quickly
        target_timeout = (
            "app.modules.server.application.commands.delete_server.DESTROY_TIMEOUT_SECONDS"
        )
        with patch(target_timeout, 0.01):
            handler = DeleteServerHandler(event_bus, provider_factory=mock_factory)
            result = await handler.handle(DeleteServerCommand(server_id="test-del-timeout-1"))

        assert result.success is True
        mock_delete_dir.assert_called_once()
        with pytest.raises(ServerNotFoundError):
            await _get_server("test-del-timeout-1")



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
                patch(
                    "app.modules.server.application.commands.import_server.SERVERS_DATA_DIR",
                    servers_root,
                ),
                patch(
                    "app.modules.server.application.commands.import_server.local_fs.delete_dir"
                ) as mock_delete,
                patch(
                    "app.modules.server.infrastructure.repository.SQLServerRepository.save",
                    side_effect=Exception("DB save failed"),
                ),
            ):
                handler = ImportServerHandler(event_bus)
                with pytest.raises(Exception, match="DB save failed"):
                    await handler.handle(
                        ImportServerCommand(
                            source_path=src_dir,
                            name="ImportFailTest",
                            minecraft_version="1.21",
                            server_type="vanilla",
                        )
                    )

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
                patch(
                    "app.modules.server.application.commands.import_server.SERVERS_DATA_DIR",
                    servers_root,
                ),
                patch(
                    "app.modules.server.application.commands.import_server.local_fs.delete_dir"
                ) as mock_delete,
            ):
                handler = ImportServerHandler(event_bus)
                result = await handler.handle(
                    ImportServerCommand(
                        source_path=src_dir,
                        name="ImportSuccessTest",
                        minecraft_version="1.21",
                        server_type="vanilla",
                    )
                )

            assert result.success is True
            mock_delete.assert_not_called()


@pytest.mark.usefixtures("init_test_db")
class TestUpdateServerConfigHandler:
    @pytest.mark.asyncio
    async def test_update_name_updates_db_and_properties_file(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        props_file = tmp_path / "server.properties"
        props_file.write_text(
            "#Minecraft server properties\nserver-name=OldName\nmotd=Initial\n", encoding="utf-8"
        )

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
        result = await handler.handle(
            UpdateServerConfigCommand(
                server_id="test-upd-name",
                name="NewRenamedServer",
                properties={"motd": "Updated MOTD", "max_players": 40},
            )
        )

        assert result.success is True
        loaded = await _get_server("test-upd-name")
        assert loaded.name == "NewRenamedServer"
        assert loaded.properties.motd == "Updated MOTD"
        assert loaded.properties.max_players == 40

        content = props_file.read_text(encoding="utf-8")
        assert "server-name=NewRenamedServer" in content
        assert "motd=Updated MOTD" in content
        assert "max-players=40" in content


@pytest.mark.usefixtures("init_test_db")
class TestRetryProvisioningHandler:
    @pytest.mark.asyncio
    async def test_retry_nonexistent_server_fails(self, event_bus: EventBus) -> None:
        handler = RetryProvisioningHandler(event_bus)
        result = await handler.handle(RetryProvisioningCommand(server_id="nonexistent-srv"))
        assert result.success is False
        assert result.error_code == "SERVER_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_retry_non_failed_status_fails(self, event_bus: EventBus, tmp_path) -> None:
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            deployment = ServerDeployment(
                location_type=LocationType.LOCAL,
                root_path=str(tmp_path),
                working_directory=".",
                startup_jar="server.jar",
            )
            server = Server.create(
                server_id=ServerId("test-retry-created"),
                name="RetryCreatedTest",
                server_type=ServerType.FORGE,
                minecraft_version=MinecraftVersion.parse("1.20.1"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments(),
                properties=ServerProperties(port=PortNumber(25565)),
                deployment=deployment,
            )
            await repo.save(server)
            await session.commit()

        handler = RetryProvisioningHandler(event_bus)
        result = await handler.handle(RetryProvisioningCommand(server_id="test-retry-created"))
        assert result.success is False
        assert result.error_code == "INVALID_STATUS"
        assert "expected 'provisioning_failed'" in result.error

    @pytest.mark.asyncio
    async def test_retry_forge_provisioning_succeeds_and_reinvokes(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            deployment = ServerDeployment(
                location_type=LocationType.LOCAL,
                root_path=str(tmp_path),
                working_directory=".",
                startup_jar="server.jar",
            )
            server = Server.create(
                server_id=ServerId("test-retry-forge"),
                name="RetryForgeTest",
                server_type=ServerType.FORGE,
                minecraft_version=MinecraftVersion.parse("1.20.1"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments(),
                properties=ServerProperties(port=PortNumber(25565)),
                deployment=deployment,
            )
            server.begin_provisioning()
            server.fail_provisioning(error="Download timed out", retryable=False)
            await repo.save(server)
            await session.commit()

        handler = RetryProvisioningHandler(event_bus)
        with patch(
            "app.modules.server.application.services.forge_provisioner.provision_forge_server"
        ) as mock_prov:
            result = await handler.handle(RetryProvisioningCommand(server_id="test-retry-forge"))
            assert result.success is True
            assert result.data["status"] == "provisioning"
            mock_prov.assert_called_once_with(
                server_id="test-retry-forge",
                minecraft_version="1.20.1",
                event_bus=event_bus,
            )

        loaded = await _get_server("test-retry-forge")
        assert loaded.status == ServerStatus.PROVISIONING
        assert loaded.provisioning_error is None
        assert loaded.provisioning_retryable is False

    @pytest.mark.asyncio
    async def test_retry_neoforge_provisioning_succeeds_and_reinvokes(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            deployment = ServerDeployment(
                location_type=LocationType.LOCAL,
                root_path=str(tmp_path),
                working_directory=".",
                startup_jar="server.jar",
            )
            server = Server.create(
                server_id=ServerId("test-retry-neoforge"),
                name="RetryNeoForgeTest",
                server_type=ServerType.NEOFORGE,
                minecraft_version=MinecraftVersion.parse("1.20.4"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments(),
                properties=ServerProperties(port=PortNumber(25565)),
                deployment=deployment,
            )
            server.begin_provisioning()
            server.fail_provisioning(error="Metadata fetch failed", retryable=False)
            await repo.save(server)
            await session.commit()

        handler = RetryProvisioningHandler(event_bus)
        with patch(
            "app.modules.server.application.services.neoforge_provisioner.provision_neoforge_server"
        ) as mock_prov:
            result = await handler.handle(RetryProvisioningCommand(server_id="test-retry-neoforge"))
            assert result.success is True
            assert result.data["status"] == "provisioning"
            mock_prov.assert_called_once_with(
                server_id="test-retry-neoforge",
                minecraft_version="1.20.4",
                event_bus=event_bus,
            )

        loaded = await _get_server("test-retry-neoforge")
        assert loaded.status == ServerStatus.PROVISIONING


@pytest.mark.usefixtures("init_test_db")
class TestGetServerConsole:
    @pytest.mark.asyncio
    async def test_console_returns_provider_logs_when_handle_exists(self) -> None:
        await _create_test_server("test-console-1", with_deployment=True)
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = await repo.get(ServerId("test-console-1"))
            server.start()
            server.record_runtime_starting(
                pid=1234,
                port=25565,
                host="127.0.0.1",
                external_id="ext-handle-1",
            )
            await repo.save(server)
            await session.commit()

        mock_prov = AsyncMock()
        mock_prov.console.return_value = ["Line 1", "Line 2"]
        with patch(
            "app.modules.server.infrastructure.providers.provider_factory.get",
            return_value=mock_prov,
        ):
            handler = GetServerConsoleHandler()
            res = await handler.handle(GetServerConsoleQuery(server_id="test-console-1", tail=50))
            assert res.lines == ["Line 1", "Line 2"]

    @pytest.mark.asyncio
    async def test_console_crashed_fallback_cached_logs(self) -> None:
        await _create_test_server("test-console-crash", with_deployment=True)
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = await repo.get(ServerId("test-console-crash"))
            server.start()
            server.record_runtime_starting(
                pid=1234,
                port=25565,
                host="127.0.0.1",
                external_id="ext-handle-crash",
            )
            server.crash(
                exit_code=1,
                last_log_lines=["Crash log 1", "Crash log 2"],
            )
            await repo.save(server)
            import json
            from datetime import UTC, datetime

            from app.modules.health.infrastructure.models import EvidenceBundleModel

            session.add(
                EvidenceBundleModel(
                    id="ev-crash-1",
                    server_id="test-console-crash",
                    latest_log_tail=json.dumps(["Crash log 1", "Crash log 2"]),
                    recorded_at=datetime.now(UTC),
                )
            )
            await session.commit()

        # When provider.console fails/raises, falls back to cached crash log lines
        mock_prov = AsyncMock()
        mock_prov.console.side_effect = RuntimeError("session closed")
        with patch(
            "app.modules.server.infrastructure.providers.provider_factory.get",
            return_value=mock_prov,
        ):
            handler = GetServerConsoleHandler()
            res = await handler.handle(GetServerConsoleQuery(server_id="test-console-crash"))
            assert res.lines == ["Crash log 1", "Crash log 2"]

    @pytest.mark.asyncio
    async def test_server_crash_preserves_external_id_and_logs(self) -> None:
        await _create_test_server("test-crash-domain", with_deployment=True)
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = await repo.get(ServerId("test-crash-domain"))
            server.start()
            server.record_runtime_starting(
                pid=999,
                port=25565,
                host="127.0.0.1",
                external_id="container-12345",
            )
            server.crash(
                exit_code=1,
                last_log_lines=["Error: Java 25 required"],
            )
            assert server.status == ServerStatus.CRASHED
            assert server.runtime.external_id == "container-12345"
            assert server.runtime.last_log_lines == ["Error: Java 25 required"]
