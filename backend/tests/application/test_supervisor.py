import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.server.application.supervisor import RuntimeSupervisor
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
from app.modules.shared.value_objects import MinecraftVersion, ServerId


@pytest.fixture
def mock_provider() -> ServerProvider:
    provider = MagicMock(spec=ServerProvider)
    provider.provider_type = "local"
    provider.wait_ready = AsyncMock(return_value=True)
    provider.verify_process = AsyncMock(return_value=True)
    provider.status = AsyncMock(return_value=ServerRuntimeStatus.RUNNING)
    provider.collect_diagnostics = AsyncMock()
    return provider


@pytest.fixture
def mock_server() -> Server:
    s = Server.create(
        server_id=ServerId("test-sup-1"),
        name="Supervised Server",
        server_type=ServerType.VANILLA,
        minecraft_version=MinecraftVersion.parse("1.21"),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(),
        properties=ServerProperties(port=PortNumber(25565)),
    )
    s.start()
    s.collect_events()
    return s


@pytest.fixture
def server_handle() -> ServerHandle:
    return ServerHandle(
        provider="local",
        server_id="test-sup-1",
        external_id="onx-test-sup-1",
    )


@pytest.mark.asyncio
class TestRuntimeSupervisor:
    async def test_start_and_stop(self, mock_provider, mock_server, server_handle):
        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()
        on_crash = MagicMock()

        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=repo_get,
            repo_save=repo_save,
            on_crash=on_crash,
            health_interval=0.1,
            startup_timeout=5.0,
        )

        assert supervisor.server_id == "test-sup-1"
        assert not supervisor.is_running

        await supervisor.start()
        assert supervisor.is_running

        await asyncio.sleep(0.2)

        await supervisor.stop()
        assert not supervisor.is_running

    async def test_health_check_detects_process_death(
        self, mock_provider, mock_server, server_handle
    ):
        mock_provider.verify_process = AsyncMock(side_effect=[True, True, False])
        mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.ERROR)
        mock_provider.collect_diagnostics = AsyncMock()

        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()
        on_crash = MagicMock()

        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=repo_get,
            repo_save=repo_save,
            on_crash=on_crash,
            health_interval=0.05,
            startup_timeout=1.0,
        )

        await supervisor.start()
        await asyncio.sleep(0.3)

        assert on_crash.called or not supervisor.is_running

        await supervisor.stop()

    async def test_start_for_and_stop_for(self, mock_provider, mock_server, server_handle):
        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()

        supervisor = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=repo_get,
            repo_save=repo_save,
            health_interval=0.1,
            startup_timeout=5.0,
        )

        assert RuntimeSupervisor.is_supervised("test-sup-1")
        assert RuntimeSupervisor.get_for("test-sup-1") is supervisor

        await RuntimeSupervisor.stop_for("test-sup-1")

        assert not RuntimeSupervisor.is_supervised("test-sup-1")

    async def test_start_for_returns_existing(self, mock_provider, mock_server, server_handle):
        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()

        s1 = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=repo_get,
            repo_save=repo_save,
        )
        s2 = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=repo_get,
            repo_save=repo_save,
        )

        assert s1 is s2

        await RuntimeSupervisor.stop_for("test-sup-1")

    async def test_uptime_and_heartbeat(self, mock_provider, mock_server, server_handle):
        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()

        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=repo_get,
            repo_save=repo_save,
            health_interval=0.05,
            startup_timeout=1.0,
        )

        assert supervisor.uptime == 0.0

        await supervisor.start()
        await asyncio.sleep(0.1)

        assert supervisor.last_heartbeat > 0
        assert supervisor.uptime > 0
        assert supervisor._ready_at_wall is not None
        assert abs(supervisor.uptime - (time.time() - supervisor._ready_at_wall)) < 0.2

        await supervisor.stop()

    async def test_handle_crash_properly_awaits_repo(
        self, mock_provider, mock_server, server_handle
    ):
        crash_spy = MagicMock(wraps=mock_server.crash)

        async def repo_get(sid):
            mock_server.crash = crash_spy
            return mock_server

        repo_save = AsyncMock()

        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=repo_get,
            repo_save=repo_save,
            health_interval=0.1,
            startup_timeout=5.0,
        )

        from app.modules.server.domain.diagnostics import FailureCode, RuntimeDiagnostics

        diag = RuntimeDiagnostics(
            failure_code=FailureCode.RUNTIME_PROCESS_LOST,
            failure_reason="test failure",
            exit_code=-1,
            last_log_lines=["test log"],
        )

        await supervisor._handle_crash(diag)

        crash_spy.assert_called_once_with(exit_code=-1, last_log_lines=["test log"])
        repo_save.assert_awaited_once()

    async def test_crash_path_persists_state_via_real_async_path(
        self, mock_provider, mock_server, server_handle
    ):
        sentinel = {"persisted": False}

        async def fake_get(sid):
            return mock_server

        async def fake_save(s):
            sentinel["persisted"] = True

        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=fake_get,
            repo_save=fake_save,
            health_interval=0.1,
            startup_timeout=5.0,
        )

        from app.modules.server.domain.diagnostics import FailureCode, RuntimeDiagnostics

        diag = RuntimeDiagnostics(
            failure_code=FailureCode.RUNTIME_PROCESS_LOST,
            failure_reason="process died",
            exit_code=137,
        )

        await supervisor._handle_crash(diag)

        assert mock_server.status.value == "crashed"
        assert sentinel["persisted"] is True

    async def test_race_stop_for_vs_in_flight_health_check(
        self, mock_provider, mock_server, server_handle
    ):
        verify_busy = asyncio.Event()

        async def cancellable_verify(handle):
            verify_busy.set()
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            try:
                await fut
            except asyncio.CancelledError:
                raise
            return False

        mock_provider.verify_process = cancellable_verify
        mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.ERROR)
        mock_provider.collect_diagnostics = AsyncMock()

        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()
        crash_spy = MagicMock(wraps=mock_server.crash)
        mock_server.crash = crash_spy

        supervisor = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=repo_get,
            repo_save=repo_save,
            health_interval=0.1,
            startup_timeout=5.0,
        )

        await asyncio.wait_for(verify_busy.wait(), timeout=2.0)

        await RuntimeSupervisor.stop_for(supervisor.server_id)

        assert not supervisor.is_running
        crash_spy.assert_not_called()

    async def test_race_health_check_completes_during_stop(
        self, mock_provider, mock_server, server_handle
    ):
        status_busy = asyncio.Event()

        async def cancellable_status(handle):
            status_busy.set()
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            try:
                await fut
            except asyncio.CancelledError:
                raise
            return ServerRuntimeStatus.ERROR

        mock_provider.verify_process = AsyncMock(return_value=False)
        mock_provider.status = cancellable_status
        mock_provider.collect_diagnostics = AsyncMock()

        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()
        crash_spy = MagicMock(wraps=mock_server.crash)
        mock_server.crash = crash_spy

        supervisor = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=repo_get,
            repo_save=repo_save,
            health_interval=0.1,
            startup_timeout=5.0,
        )

        await asyncio.wait_for(status_busy.wait(), timeout=2.0)

        await RuntimeSupervisor.stop_for(supervisor.server_id)

        assert not supervisor.is_running
        crash_spy.assert_not_called()
