"""Tests for stale startup deadline and supervisor reuse prevention.

Covers:
A. tests/application/test_stale_startup_deadline.py:
   - restart gets a fresh startup window: short injected startup_timeout (~0.3 s),
     alive-never-ready fake provider; assert run #2 time-to-RUNNING ~= run #1
     (not ~0 s).
   - start_for reuse must not keep the old handle: expect the new handle.
B. timeout-kill path then immediate start_for: run #1 hits STARTUP_TIMEOUT
   via _handle_crash, then call start_for again before/while _run's finally
   runs; assert run #2 gets a full fresh window and the new handle.
C. stop() then start_for immediately: no reuse of the stopped instance.
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


@pytest.fixture(autouse=True)
def clean_supervisor_instances():
    """Ensure supervisor singleton dictionary is clean before and after each test."""
    RuntimeSupervisor._instances.clear()
    yield
    RuntimeSupervisor._instances.clear()


@pytest.fixture
def mock_server() -> Server:
    s = Server.create(
        server_id=ServerId("test-stale-srv-1"),
        name="Stale Deadline Server",
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
def handle_run1() -> ServerHandle:
    return ServerHandle(
        provider="local",
        server_id="test-stale-srv-1",
        external_id="onx-test-stale-run1",
        metadata={"pid": 11111, "port": 25565, "server_name": "Stale Deadline Server"},
    )


@pytest.fixture
def handle_run2() -> ServerHandle:
    return ServerHandle(
        provider="local",
        server_id="test-stale-srv-1",
        external_id="onx-test-stale-run2",
        metadata={"pid": 22222, "port": 25565, "server_name": "Stale Deadline Server"},
    )


@pytest.mark.asyncio
class TestStaleStartupDeadline:
    async def test_restart_gets_fresh_startup_window(
        self, mock_server: Server, handle_run1: ServerHandle
    ) -> None:
        """Test A1: restart gets a fresh startup window.

        Inject short startup_timeout (~0.3s) and an alive-never-ready fake provider.
        Assert run #2 time-to-RUNNING ~= run #1 (not ~0s).
        """
        provider = MagicMock(spec=ServerProvider)
        provider.provider_type = "local"
        provider.wait_ready = AsyncMock(return_value=False)
        provider.verify_process = AsyncMock(return_value=True)
        provider.status = AsyncMock(return_value=ServerRuntimeStatus.RUNNING)
        provider.get_address = AsyncMock(return_value="127.0.0.1")

        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()

        current_time = 1000.0

        def fake_monotonic() -> float:
            return current_time

        async def fake_sleep(duration: float) -> None:
            nonlocal current_time
            current_time += min(duration, 0.1)

        with (
            patch("time.monotonic", side_effect=fake_monotonic),
            patch(
                "app.modules.server.application.supervisor.asyncio.sleep",
                side_effect=fake_sleep,
            ),
        ):
            supervisor = RuntimeSupervisor(
                server=mock_server,
                provider=provider,
                handle=handle_run1,
                repo_get=repo_get,
                repo_save=repo_save,
                health_interval=0.05,
                startup_timeout=0.3,
            )

            # Run #1
            t1_start = current_time
            await supervisor._verify_startup()
            t1_duration = current_time - t1_start
            assert t1_duration >= 0.3
            assert mock_server.status == ServerStatus.RUNNING

            # Advance simulated time between runs (e.g. server offline for 15s)
            current_time += 15.0
            mock_server.mark_stopped()
            mock_server.start()
            assert mock_server.status == ServerStatus.STARTING

            # Run #2: restart on the supervisor instance
            # start() must re-anchor _started_at = time.monotonic()
            await supervisor.start()
            if supervisor._task:
                supervisor._task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await supervisor._task

            t2_start = current_time
            await supervisor._verify_startup()
            t2_duration = current_time - t2_start

            assert mock_server.status == ServerStatus.RUNNING
            # On HEAD: _started_at was NOT updated in start(), so deadline is still
            # 1000.0 + 0.3 = 1000.3, which expired at 1015.0. _verify_startup exits
            # immediately with t2_duration = 0.0s.
            assert t2_duration >= 0.25, (
                f"Run #2 deadline was stale! t2_duration={t2_duration:.2f}s, "
                f"t1_duration={t1_duration:.2f}s (expected fresh ~0.3s window)"
            )
            assert abs(t2_duration - t1_duration) < 0.15

    async def test_start_for_reuse_does_not_keep_old_handle(
        self, mock_server: Server, handle_run1: ServerHandle, handle_run2: ServerHandle
    ) -> None:
        """Test A2: start_for reuse must not keep the old handle.

        Expect the new handle when start_for is invoked with a different handle.
        """
        mock_provider = MagicMock(spec=ServerProvider)
        mock_provider.provider_type = "local"
        mock_provider.wait_ready = AsyncMock(return_value=True)
        mock_provider.verify_process = AsyncMock(return_value=True)

        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()

        s1 = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=handle_run1,
            repo_get=repo_get,
            repo_save=repo_save,
        )
        assert s1._handle == handle_run1

        # Run #2 with different handle
        s2 = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=handle_run2,
            repo_get=repo_get,
            repo_save=repo_save,
        )

        assert s2 is not s1, "start_for reused the old supervisor instance despite handle change!"
        assert s2._handle == handle_run2, f"Expected {handle_run2}, got {s2._handle}"
        assert RuntimeSupervisor.get_for(str(s1.server_id)) is s2

        await s2.stop()

    async def test_timeout_kill_path_immediate_start_for(
        self, mock_server: Server, handle_run1: ServerHandle, handle_run2: ServerHandle
    ) -> None:
        """Test B: timeout-kill path then immediate start_for.

        Run #1 hits STARTUP_TIMEOUT via _handle_crash, then call start_for again
        before/while _run's finally runs; assert run #2 gets a full fresh window
        and the new handle.
        """
        mock_provider = MagicMock(spec=ServerProvider)
        mock_provider.provider_type = "local"
        mock_provider.wait_ready = AsyncMock(return_value=True)
        mock_provider.verify_process = AsyncMock(return_value=True)
        mock_provider.collect_diagnostics = AsyncMock(
            return_value=RuntimeDiagnostics(
                provider="local",
                exit_code=1,
                failure_code=FailureCode.STARTUP_TIMEOUT,
                failure_reason="Startup timeout",
            )
        )

        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()

        s1 = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=handle_run1,
            repo_get=repo_get,
            repo_save=repo_save,
            startup_timeout=10.0,
        )

        # Trigger STARTUP_TIMEOUT via _handle_crash
        diag = RuntimeDiagnostics(
            provider="local",
            exit_code=1,
            failure_code=FailureCode.STARTUP_TIMEOUT,
            failure_reason="Process died during startup verification",
        )
        await s1._handle_crash(diag)

        # In unpatched code: _stop_event is set, but _active is NOT cleared!
        # Calling start_for immediately before _run's finally completes must NOT return s1.
        s2 = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=handle_run2,
            repo_get=repo_get,
            repo_save=repo_save,
            startup_timeout=10.0,
        )

        assert s2 is not s1, "start_for reused the crashed/dying supervisor instance!"
        assert s2._handle == handle_run2
        assert s2._active is True
        assert not s2._stop_event.is_set()
        assert RuntimeSupervisor.get_for(str(mock_server.id)) is s2

        # When s1's task finishes and cleans up, s1 must NOT pop s2 from _instances
        if s1._task:
            with contextlib.suppress(Exception):
                await s1._task
        assert RuntimeSupervisor.get_for(str(mock_server.id)) is s2

        await s2.stop()

    async def test_stop_then_immediate_start_for_no_reuse(
        self, mock_server: Server, handle_run1: ServerHandle
    ) -> None:
        """Test C: stop() then start_for immediately: no reuse of the stopped instance.

        Calling stop() and then immediately start_for() must never return the stopped instance,
        and s1's cleanup must not pop s2 from registry.
        """
        mock_provider = MagicMock(spec=ServerProvider)
        mock_provider.provider_type = "local"
        mock_provider.wait_ready = AsyncMock(return_value=True)
        mock_provider.verify_process = AsyncMock(return_value=True)

        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()

        s1 = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=handle_run1,
            repo_get=repo_get,
            repo_save=repo_save,
        )

        # Initiate stop on s1
        stop_task = asyncio.create_task(s1.stop())
        await asyncio.sleep(0)  # let stop() start and set stop_event

        # Call start_for immediately with handle_run1
        s2 = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=handle_run1,
            repo_get=repo_get,
            repo_save=repo_save,
        )

        assert s2 is not s1, "start_for reused the stopping supervisor instance!"
        assert s2._active is True
        assert not s2._stop_event.is_set()
        assert RuntimeSupervisor.get_for(str(mock_server.id)) is s2

        await stop_task
        # Verify s1's post-stop cleanup did not pop s2
        assert RuntimeSupervisor.get_for(str(mock_server.id)) is s2

        await s2.stop()

    async def test_suspend_old_run_register_new_pins_is_self_pop_guard(
        self, mock_server: Server, handle_run1: ServerHandle, handle_run2: ServerHandle
    ) -> None:
        """Requirement 2.b: Suspend old _run mid-verify on an Event, register the new supervisor,
        release old task, assert registry still holds new one (pins 'is self' pop guard).
        """
        suspend_event = asyncio.Event()
        resume_event = asyncio.Event()

        mock_provider1 = MagicMock(spec=ServerProvider)
        mock_provider1.provider_type = "local"

        async def _hang_wait_ready(*_args, **_kwargs):
            suspend_event.set()
            await resume_event.wait()
            return False

        mock_provider1.wait_ready = AsyncMock(side_effect=_hang_wait_ready)
        mock_provider1.verify_process = AsyncMock(return_value=True)

        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()

        s1 = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider1,
            handle=handle_run1,
            repo_get=repo_get,
            repo_save=repo_save,
            startup_timeout=5.0,
        )

        # Wait until s1._run reaches wait_ready and suspends mid-verify
        await asyncio.wait_for(suspend_event.wait(), timeout=2.0)
        assert RuntimeSupervisor.get_for(str(mock_server.id)) is s1

        # Register new supervisor s2
        mock_provider2 = MagicMock(spec=ServerProvider)
        mock_provider2.provider_type = "local"
        mock_provider2.wait_ready = AsyncMock(return_value=True)
        mock_provider2.verify_process = AsyncMock(return_value=True)

        s2 = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider2,
            handle=handle_run2,
            repo_get=repo_get,
            repo_save=repo_save,
        )
        assert s2 is not s1
        assert RuntimeSupervisor.get_for(str(mock_server.id)) is s2

        # Now release s1's hanging _run task to let it exit its loop and execute its finally: block
        resume_event.set()
        if s1._task:
            with contextlib.suppress(Exception):
                await s1._task

        # Crucial assertion: s1's finally block had:
        # if self._instances.get(self._server_id) is self:
        #     self._instances.pop(self._server_id, None)
        # It must NOT have popped s2!
        assert RuntimeSupervisor.get_for(str(mock_server.id)) is s2

        await s2.stop()

    async def test_differing_handle_schedules_stop_of_old_instance(
        self, mock_server: Server, handle_run1: ServerHandle, handle_run2: ServerHandle
     ) -> None:
        """Requirement 2.c: start_for with differing handle cancels old task and schedules stop."""
        mock_provider = MagicMock(spec=ServerProvider)
        mock_provider.provider_type = "local"
        mock_provider.wait_ready = AsyncMock(return_value=True)
        mock_provider.verify_process = AsyncMock(return_value=True)

        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock()

        s1 = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=handle_run1,
            repo_get=repo_get,
            repo_save=repo_save,
        )
        await asyncio.sleep(0.01)
        assert s1.is_running is True
        assert s1._active is True
        assert not s1._stop_event.is_set()

        # Call start_for with different handle and verify s1.stop is scheduled
        with patch.object(s1, "stop", wraps=s1.stop) as spy_stop:
            s2 = RuntimeSupervisor.start_for(
                server=mock_server,
                provider=mock_provider,
                handle=handle_run2,
                repo_get=repo_get,
                repo_save=repo_save,
            )

            # Assert s1 was marked inactive and stop_event set immediately
            assert s1._active is False
            assert s1._stop_event.is_set()
            assert s1._task is not None
            # Task has cancellation requested
            is_cancelling = (
                s1._task.cancelling() > 0
                if hasattr(s1._task, "cancelling")
                else s1._task.cancelled()
            )
            assert is_cancelling or s1._task.done()

            # Allow scheduled stop on event loop to run
            await asyncio.sleep(0.05)
            assert s1._task.done()
            spy_stop.assert_called_once()

        # s2 is the active supervisor in registry
        assert RuntimeSupervisor.get_for(str(mock_server.id)) is s2
        assert s2.is_running is True

        await s2.stop()

    async def test_active_flag_cleared_during_in_flight_crash_handling(
        self, mock_server: Server, handle_run1: ServerHandle, handle_run2: ServerHandle
    ) -> None:
        """Requirement 2.d: _active is cleared immediately upon entry to _handle_crash so that
        concurrent start_for() cannot observe a crashing instance as active while async crash
        persistence is still in flight.
        """
        crash_in_flight = asyncio.Event()
        release_crash = asyncio.Event()

        mock_provider = MagicMock(spec=ServerProvider)
        mock_provider.provider_type = "local"
        mock_provider.wait_ready = AsyncMock(return_value=True)
        mock_provider.verify_process = AsyncMock(return_value=True)

        async def _slow_repo_save(_server):
            crash_in_flight.set()
            await release_crash.wait()

        repo_get = AsyncMock(return_value=mock_server)
        repo_save = AsyncMock(side_effect=_slow_repo_save)

        s1 = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=handle_run1,
            repo_get=repo_get,
            repo_save=repo_save,
        )

        diag = RuntimeDiagnostics(
            provider="local",
            exit_code=137,
            failure_code=FailureCode.RUNTIME_PROCESS_LOST,
            failure_reason="OOMKilled",
        )

        # Launch crash handling in background
        crash_task = asyncio.create_task(s1._handle_crash(diag))

        # Wait until crash handling starts persisting
        await asyncio.wait_for(crash_in_flight.wait(), timeout=2.0)

        # At this point, crash persistence is still awaiting release_crash,
        # but _active MUST ALREADY BE FALSE
        assert s1._active is False

        # If a start_for call arrives right now, it must NOT reuse s1 as active
        s2 = RuntimeSupervisor.start_for(
            server=mock_server,
            provider=mock_provider,
            handle=handle_run2,
            repo_get=repo_get,
            repo_save=repo_save,
        )
        assert s2 is not s1
        assert s2._active is True

        # Now complete crash persistence
        release_crash.set()
        await crash_task

        # s2 is still the registered supervisor
        assert RuntimeSupervisor.get_for(str(mock_server.id)) is s2
        await s2.stop()
