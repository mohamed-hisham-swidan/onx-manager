import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ProviderError
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.diagnostics import FailureCode, RuntimeDiagnostics
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


@pytest.mark.asyncio
class TestHealthCheckExceptionBoundary:
    async def test_health_check_healthy_updates_heartbeat(
        self, mock_provider, mock_server, server_handle
    ):
        mock_provider.verify_process = AsyncMock(return_value=True)
        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=AsyncMock(return_value=mock_server),
            repo_save=AsyncMock(),
        )
        old_heartbeat = supervisor._last_heartbeat - 10.0
        supervisor._last_heartbeat = old_heartbeat

        await supervisor._health_check()

        assert supervisor._last_heartbeat > old_heartbeat
        assert not supervisor._stop_event.is_set()

    async def test_health_check_stopped_graceful_exit(
        self, mock_provider, mock_server, server_handle
    ):
        mock_provider.verify_process = AsyncMock(return_value=False)
        mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.STOPPED)
        diag = RuntimeDiagnostics(provider="local")
        mock_provider.collect_diagnostics = AsyncMock(return_value=diag)

        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()

        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=repo_get,
            repo_save=repo_save,
        )
        supervisor._handle_crash = AsyncMock()

        await supervisor._health_check()

        assert supervisor._stop_event.is_set()
        supervisor._handle_crash.assert_not_called()
        mock_provider.collect_diagnostics.assert_awaited_once()
        repo_save.assert_awaited_once_with(mock_server)
        assert mock_server.status == ServerStatus.STOPPED

    async def test_health_check_stopped_from_running_persists_to_repo(
        self, mock_provider, mock_server, server_handle
    ):
        # Server starts in RUNNING
        mock_server.mark_running(pid=1234, port=25565)
        assert mock_server.status == ServerStatus.RUNNING

        mock_provider.verify_process = AsyncMock(return_value=False)
        mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.STOPPED)
        diag = RuntimeDiagnostics(provider="local", exit_code=0)
        mock_provider.collect_diagnostics = AsyncMock(return_value=diag)

        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()

        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=repo_get,
            repo_save=repo_save,
        )
        supervisor._handle_crash = AsyncMock()

        await supervisor._health_check()

        assert supervisor._stop_event.is_set()
        supervisor._handle_crash.assert_not_called()
        repo_save.assert_awaited_once_with(mock_server)
        assert mock_server.status == ServerStatus.STOPPED

    async def test_health_check_not_alive_collects_diag_and_crashes(
        self, mock_provider, mock_server, server_handle
    ):
        mock_provider.verify_process = AsyncMock(return_value=False)
        mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.ERROR)
        diag = RuntimeDiagnostics(provider="local")
        mock_provider.collect_diagnostics = AsyncMock(return_value=diag)

        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=AsyncMock(return_value=mock_server),
            repo_save=AsyncMock(),
        )
        supervisor._handle_crash = AsyncMock()

        await supervisor._health_check()

        supervisor._handle_crash.assert_awaited_once()
        crashed_diag = supervisor._handle_crash.call_args[0][0]
        assert crashed_diag.failure_code == FailureCode.RUNTIME_PROCESS_LOST
        assert "Runtime process lost" in crashed_diag.failure_reason

    async def test_health_check_provider_error_with_successful_diagnostics(
        self, mock_provider, mock_server, server_handle
    ):
        mock_provider.verify_process = AsyncMock(
            side_effect=ProviderError("local", "verify_process", "tmux session lost")
        )
        diag = RuntimeDiagnostics(provider="local")
        mock_provider.collect_diagnostics = AsyncMock(return_value=diag)

        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=AsyncMock(return_value=mock_server),
            repo_save=AsyncMock(),
        )
        supervisor._handle_crash = AsyncMock()

        await supervisor._health_check()

        supervisor._handle_crash.assert_awaited_once()
        crashed_diag = supervisor._handle_crash.call_args[0][0]
        assert crashed_diag.failure_code == FailureCode.RUNTIME_PROCESS_LOST
        assert "Provider error during health check" in crashed_diag.failure_reason
        assert "tmux session lost" in crashed_diag.failure_reason

    async def test_health_check_provider_error_with_failing_diagnostics(
        self, mock_provider, mock_server, server_handle
    ):
        mock_provider.verify_process = AsyncMock(
            side_effect=ProviderError("local", "verify_process", "tmux missing")
        )
        mock_provider.collect_diagnostics = AsyncMock(
            side_effect=RuntimeError("collect_diagnostics crashed")
        )

        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=AsyncMock(return_value=mock_server),
            repo_save=AsyncMock(),
        )
        supervisor._handle_crash = AsyncMock()

        await supervisor._health_check()

        supervisor._handle_crash.assert_awaited_once()
        crashed_diag = supervisor._handle_crash.call_args[0][0]
        assert crashed_diag.provider == "local"
        assert crashed_diag.failure_code == FailureCode.RUNTIME_PROCESS_LOST
        assert "Provider error during health check" in crashed_diag.failure_reason
        assert "tmux missing" in crashed_diag.failure_reason

    async def test_health_check_unexpected_exception_with_successful_diagnostics(
        self, mock_provider, mock_server, server_handle
    ):
        mock_provider.verify_process = AsyncMock(side_effect=RuntimeError("Kernel error"))
        diag = RuntimeDiagnostics(provider="local")
        mock_provider.collect_diagnostics = AsyncMock(return_value=diag)

        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=AsyncMock(return_value=mock_server),
            repo_save=AsyncMock(),
        )
        supervisor._handle_crash = AsyncMock()

        await supervisor._health_check()

        supervisor._handle_crash.assert_awaited_once()
        crashed_diag = supervisor._handle_crash.call_args[0][0]
        assert crashed_diag.failure_code == FailureCode.RUNTIME_PROCESS_LOST
        assert "Unexpected error during health check" in crashed_diag.failure_reason

    async def test_health_check_unexpected_exception_with_failing_diagnostics(
        self, mock_provider, mock_server, server_handle
    ):
        mock_provider.verify_process = AsyncMock(side_effect=RuntimeError("Kernel error"))
        mock_provider.collect_diagnostics = AsyncMock(
            side_effect=Exception("Disk error during diag")
        )

        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=AsyncMock(return_value=mock_server),
            repo_save=AsyncMock(),
        )
        supervisor._handle_crash = AsyncMock()

        await supervisor._health_check()

        supervisor._handle_crash.assert_awaited_once()
        crashed_diag = supervisor._handle_crash.call_args[0][0]
        assert crashed_diag.provider == "local"
        assert crashed_diag.failure_code == FailureCode.RUNTIME_PROCESS_LOST
        assert "Unexpected error during health check" in crashed_diag.failure_reason

    async def test_stop_detaches_when_task_ignores_cancellation(
        self, mock_provider, mock_server, server_handle
    ):
        """stop() returns promptly when the task is slow to observe cancel.

        Covers the slow-observer path: the task swallows the cancel request
        but exits once it sees the stop event, so stop() reaps it without
        hitting the timeout. (Pre-fix this also passed once the event was
        observed — the timeout path below is the true regression guard.)
        """
        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=AsyncMock(return_value=mock_server),
            repo_save=AsyncMock(),
            health_interval=0.05,
            startup_timeout=1.0,
        )

        async def _swallow_cancellation_until_stopped() -> None:
            while not supervisor._stop_event.is_set():
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    continue

        supervisor._active = True
        RuntimeSupervisor._instances[supervisor.server_id] = supervisor
        supervisor._task = asyncio.create_task(_swallow_cancellation_until_stopped())
        # Let the stubborn task take its first step so cancellation is delivered
        # in-flight (and swallowed) rather than pre-start. Without the fix,
        # stop() would hang here forever awaiting the unresponsive task.
        await asyncio.sleep(0)

        await asyncio.wait_for(supervisor.stop(timeout=0.2), timeout=5)

        assert not RuntimeSupervisor.is_supervised(supervisor.server_id)
        # The stop event was set first, so the stubborn task exits on its own
        # once it observes it — reap it cleanly with no leaked pending task.
        if not supervisor._task.done():
            await asyncio.wait_for(supervisor._task, timeout=5)
        assert supervisor._task.done()

    async def test_stop_timeout_fires_for_truly_wedged_task(
        self, mock_provider, mock_server, server_handle
    ):
        """stop() detaches after `timeout` even if the task never exits.

        Regression guard for the Windows CI stall (backend-windows job wedged
        ~39 min in TestServers::test_stop_server): the only unbounded await in
        the stop path was a bare `await self._task`, which hangs forever when
        the task swallows cancellation — and a bare wait_for() around it does
        NOT help (the timeout wakeup is lost into the inner task via
        Task._fut_waiter mechanics, verified by probe on 3.12 and 3.14).
        stop() therefore waits through shield() and detaches on expiry.
        Pre-fix code hangs this test (it never accepts the `timeout` kwarg,
        and the unbounded await never returns while the wedge is held).
        """
        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=AsyncMock(return_value=mock_server),
            repo_save=AsyncMock(),
            health_interval=0.05,
            startup_timeout=1.0,
        )

        async def _wedged_until_released() -> None:
            # Ignores cancellation AND keeps running while `release` is unset,
            # so stop()'s timeout path genuinely fires — yet exits promptly
            # once released, leaving no pending task behind at teardown.
            while not release.is_set():
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    continue

        release = asyncio.Event()
        supervisor._active = True
        RuntimeSupervisor._instances[supervisor.server_id] = supervisor
        supervisor._task = asyncio.create_task(_wedged_until_released())
        await asyncio.sleep(0)

        await asyncio.wait_for(supervisor.stop(timeout=0.2), timeout=5)

        assert not RuntimeSupervisor.is_supervised(supervisor.server_id)
        # Release the wedge and reap cleanly — no leaked pending task.
        release.set()
        await asyncio.wait_for(supervisor._task, timeout=5)
        assert supervisor._task.done()

    async def test_reattach_to_running_server_preserves_running_start_time(
        self, mock_provider, mock_server, server_handle
    ):
        """Re-attaching RuntimeSupervisor to an already-RUNNING server preserves uptime."""
        mock_server.mark_running(pid=1234, port=25565, host="127.0.0.1")
        persisted_start = time.time() - 3600.0
        mock_server.runtime.running_start_time = persisted_start

        supervisor = RuntimeSupervisor(
            server=mock_server,
            provider=mock_provider,
            handle=server_handle,
            repo_get=AsyncMock(return_value=mock_server),
            repo_save=AsyncMock(),
            health_interval=0.05,
            startup_timeout=1.0,
        )

        # Immediately preserves persisted uptime before & after start()
        assert 3590.0 <= supervisor.uptime <= 3610.0

        await supervisor.start()
        await asyncio.sleep(0.1)

        assert 3590.0 <= supervisor.uptime <= 3615.0
        assert supervisor._ready_at_wall == persisted_start

        await supervisor.stop()
