"""Unit and integration tests for Playit process lifecycle, deterministic paths, and orphans.

Verifies Design Spec Revision 2.0 (SPEC-PLAYIT-LIFECYCLE-001):
  - T-PL-01: Uvicorn reload re-attachment across simulated supervisor instances
  - T-PL-02: Graceful shutdown cleanup (SIGTERM, file unlinking, lock release)
  - T-PL-03: Unresponsive daemon socket probe failure -> SIGTERM/SIGKILL -> recovery
  - T-PL-04: Dead PID in stale PID file cleanup
  - T-PL-05: Recycled PID collision prevention (cmdline mismatch safety)
  - T-PL-06: Cross-process file lock mutual exclusion
  - T-PL-07: Startup reconciliation bounded timeout
  - T-PL-08: Directory and permission failure handling
  - T-PL-09: ResetAgentHandler daemon teardown
  - T-PL-10: RemoveCredentialsHandler daemon teardown
  - T-PL-11: CloudflaredSupervisor lifespan teardown
  - T-PL-12: Same-process concurrency regression check
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.event_bus import EventBus
from app.modules.exposure.application.commands import (
    RemoveCredentialsCommand,
    RemoveCredentialsHandler,
    ResetAgentCommand,
    ResetAgentHandler,
)
from app.modules.exposure.domain.value_objects import ExposureStatus
from app.modules.exposure.infrastructure.cloudflared import (
    CloudflaredSupervisor,
    reset_cloudflared_supervisor,
)
from app.modules.exposure.infrastructure.playit_agent import (
    FileLock,
    PlayitAgentSupervisor,
    get_playit_supervisor,
    reset_playit_supervisor,
)


def _mock_subprocess(*, pid: int = 12345) -> MagicMock:
    proc = MagicMock(spec=asyncio.subprocess.Process)
    proc.pid = pid
    proc.returncode = None
    proc.wait = AsyncMock(return_value=0)
    proc.terminate = MagicMock()
    proc.kill = MagicMock()

    stdout = AsyncMock()
    stdout.readline = AsyncMock(return_value=b"")
    proc.stdout = stdout

    stderr = AsyncMock()
    stderr.readline = AsyncMock(return_value=b"")
    proc.stderr = stderr
    return proc


class TestPlayitProcessLifecycle:
    @pytest.fixture(autouse=True)
    def _cleanup_singletons(self) -> None:
        reset_playit_supervisor()
        reset_cloudflared_supervisor()
        yield
        reset_playit_supervisor()
        reset_cloudflared_supervisor()

    async def test_t_pl_01_uvicorn_reload_reattachment_healthy(self, tmp_path: Path) -> None:
        """T-PL-01: Re-attaches to live, healthy daemon without spawning duplicate."""
        run_dir = tmp_path / "run" / "playit"
        supervisor1 = PlayitAgentSupervisor(run_dir=run_dir, health_interval=0.1)
        proc = _mock_subprocess(pid=22334)

        try:
            with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
                await supervisor1.start(secret=b"test-secret-bytes")
                assert supervisor1.is_running is True
                assert supervisor1.pid == 22334
                assert supervisor1.pid_file_path.exists()
                assert supervisor1.pid_file_path.read_text().strip() == "22334"
                assert supervisor1.secret_file_path.exists()
                assert mock_exec.call_count == 1

            # Simulate reload: create supervisor2 against the same run_dir
            supervisor2 = PlayitAgentSupervisor(run_dir=run_dir, health_interval=0.1)
            assert supervisor2.is_running is False  # in-memory state fresh

            with (
                patch(
                    "app.modules.exposure.infrastructure.playit_agent._is_pid_alive_and_playit",
                    return_value=True,
                ),
                patch(
                    "app.modules.exposure.infrastructure.playit_agent._probe_unix_socket",
                    new_callable=AsyncMock,
                    return_value=True,
                ),
                patch("asyncio.create_subprocess_exec") as mock_exec2,
            ):
                reconciled = await supervisor2.reconcile_startup()
                assert reconciled is True
                assert supervisor2.is_running is True
                assert supervisor2.pid == 22334
                assert supervisor2.status == ExposureStatus.ACTIVE
                assert mock_exec2.call_count == 0  # Zero duplicate spawns!
        finally:
            await supervisor1.stop()
            if supervisor2.is_running:
                await supervisor2.stop()

    async def test_t_pl_02_graceful_shutdown_cleanup(self, tmp_path: Path) -> None:
        """T-PL-02: Graceful stop terminates process and unlinks all deterministic files."""
        run_dir = tmp_path / "run" / "playit"
        supervisor = PlayitAgentSupervisor(run_dir=run_dir, health_interval=0.1)
        proc = _mock_subprocess(pid=33445)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            await supervisor.start(secret=b"test-secret-bytes")
            assert supervisor.is_running is True
            assert supervisor.pid_file_path.exists()
            assert supervisor.secret_file_path.exists()

            await supervisor.stop()
            assert supervisor.is_running is False
            assert supervisor.status == ExposureStatus.STOPPED
            assert not supervisor.pid_file_path.exists()
            assert not supervisor.secret_file_path.exists()
            assert not supervisor.socket_path.exists()

    async def test_t_pl_03_unresponsive_socket_probe_failure_terminates_and_recovers(
        self, tmp_path: Path
    ) -> None:
        """T-PL-03: Process alive but unresponsive socket triggers termination."""
        run_dir = tmp_path / "run" / "playit"
        run_dir.mkdir(parents=True, exist_ok=True)
        pid_file = run_dir / "agent.pid"
        pid_file.write_text("44556", encoding="utf-8")
        (run_dir / "agent.sock").touch()

        supervisor = PlayitAgentSupervisor(run_dir=run_dir, health_interval=0.1)

        with (
            patch(
                "app.modules.exposure.infrastructure.playit_agent._is_pid_alive_and_playit",
                return_value=True,
            ),
            patch(
                "app.modules.exposure.infrastructure.playit_agent._probe_unix_socket",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch.object(supervisor, "_terminate_pid_direct", new_callable=AsyncMock) as mock_term,
        ):
            reconciled = await supervisor.reconcile_startup()
            assert reconciled is False
            assert supervisor.is_running is False
            mock_term.assert_called_once_with(44556)
            assert not pid_file.exists()
            assert not (run_dir / "agent.sock").exists()

    async def test_t_pl_04_dead_pid_stale_file_cleanup(self, tmp_path: Path) -> None:
        """T-PL-04: Stale PID file with dead PID is cleaned up without error."""
        run_dir = tmp_path / "run" / "playit"
        run_dir.mkdir(parents=True, exist_ok=True)
        pid_file = run_dir / "agent.pid"
        pid_file.write_text("99999", encoding="utf-8")
        secret_file = run_dir / "agent.secret"
        secret_file.write_text("stale-secret", encoding="utf-8")

        supervisor = PlayitAgentSupervisor(run_dir=run_dir, health_interval=0.1)

        with patch(
            "app.modules.exposure.infrastructure.playit_agent._is_pid_alive_and_playit",
            return_value=False,
        ):
            reconciled = await supervisor.reconcile_startup()
            assert reconciled is False
            assert supervisor.is_running is False
            assert not pid_file.exists()
            assert not secret_file.exists()

    async def test_t_pl_05_recycled_pid_mismatch_prevents_reattach(self, tmp_path: Path) -> None:
        """T-PL-05: Stale PID reused by unrelated process is detected and cleaned up safely."""
        run_dir = tmp_path / "run" / "playit"
        run_dir.mkdir(parents=True, exist_ok=True)
        pid_file = run_dir / "agent.pid"
        pid_file.write_text("11223", encoding="utf-8")

        supervisor = PlayitAgentSupervisor(run_dir=run_dir, health_interval=0.1)

        # PID 11223 is alive on OS, but cmdline check returns False (it's nginx/python, not playit)
        with patch(
            "app.modules.exposure.infrastructure.playit_agent._is_pid_alive_and_playit",
            return_value=False,
        ):
            reconciled = await supervisor.reconcile_startup()
            assert reconciled is False
            assert supervisor.is_running is False
            assert not pid_file.exists()

    def test_t_pl_06_file_lock_mutual_exclusion(self, tmp_path: Path) -> None:
        """T-PL-06: FileLock provides non-blocking cross-process mutual exclusion."""
        lock_path = tmp_path / "test.lock"
        lock1 = FileLock(lock_path)
        lock2 = FileLock(lock_path)

        assert lock1.acquire(timeout=0.5) is True
        # Second acquire fails while lock1 is held
        assert lock2.acquire(timeout=0.1) is False

        lock1.release()
        # Now lock2 can acquire
        assert lock2.acquire(timeout=0.5) is True
        lock2.release()

    async def test_t_pl_07_startup_reconciliation_bounded_timeout(self, tmp_path: Path) -> None:
        """T-PL-07: Reconciliation cannot hang boot; aborts within timeout ceiling."""
        run_dir = tmp_path / "run" / "playit"
        supervisor = PlayitAgentSupervisor(run_dir=run_dir, health_interval=0.1)

        async def _hanging_reconcile() -> bool:
            await asyncio.sleep(10.0)
            return True

        with patch.object(
            supervisor, "_reconcile_startup_internal", side_effect=_hanging_reconcile
        ):
            start = asyncio.get_event_loop().time()
            result = await supervisor.reconcile_startup()
            duration = asyncio.get_event_loop().time() - start

            assert result is False
            assert duration < 2.5  # Timed out cleanly near 2.0s

    async def test_t_pl_08_directory_permission_failure_handling(self, tmp_path: Path) -> None:
        """T-PL-08: Directory permission failures set status=ERROR with actionable error message."""
        run_dir = tmp_path / "uncreatable" / "run"
        supervisor = PlayitAgentSupervisor(run_dir=run_dir, health_interval=0.1)

        with patch.object(Path, "mkdir", side_effect=PermissionError("Permission denied")):
            with pytest.raises(PermissionError):
                await supervisor.start(secret=b"my-secret")

            assert supervisor.status == ExposureStatus.ERROR
            assert supervisor.error_message is not None
            assert "Permission denied" in supervisor.error_message

    async def test_t_pl_09_reset_agent_handler_stops_supervisor(self, tmp_path: Path) -> None:
        """T-PL-09: ResetAgentHandler executes supervisor.stop in post_commit."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        import app.modules.exposure.infrastructure.models  # noqa: F401
        from app.core.persistence.base import Base
        from app.core.persistence.db import database

        test_db = tmp_path / "test_reset.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{test_db}")
        session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        database._engine = engine
        database._session_factory = session_factory

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        try:
            event_bus = EventBus()
            handler = ResetAgentHandler(event_bus)

            supervisor = get_playit_supervisor()
            supervisor.stop = AsyncMock()  # type: ignore[method-assign]

            res = await handler.handle(ResetAgentCommand())
            assert res.success is True
            supervisor.stop.assert_awaited_once()
        finally:
            await engine.dispose()

    async def test_t_pl_10_remove_credentials_handler_stops_supervisor(
        self, tmp_path: Path
    ) -> None:
        """T-PL-10: RemoveCredentialsHandler executes supervisor.stop in post_commit."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        import app.modules.exposure.infrastructure.models  # noqa: F401
        from app.core.persistence.base import Base
        from app.core.persistence.db import database

        test_db = tmp_path / "test_remove.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{test_db}")
        session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        database._engine = engine
        database._session_factory = session_factory

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        try:
            event_bus = EventBus()
            handler = RemoveCredentialsHandler(event_bus)

            supervisor = get_playit_supervisor()
            supervisor.stop = AsyncMock()  # type: ignore[method-assign]

            res = await handler.handle(RemoveCredentialsCommand())
            assert res.success is True
            supervisor.stop.assert_awaited_once()
        finally:
            await engine.dispose()

    async def test_t_pl_11_cloudflared_supervisor_stop(self) -> None:
        """T-PL-11: CloudflaredSupervisor cleanly stops when teardown is invoked."""
        supervisor = CloudflaredSupervisor()
        proc = _mock_subprocess(pid=77889)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            await supervisor.start(token=b"fake-cf-token")
            assert supervisor.is_running is True

            await supervisor.stop()
            assert supervisor.is_running is False
            assert supervisor.status == ExposureStatus.STOPPED

    async def test_t_pl_12_concurrent_start_idempotency_regression(self, tmp_path: Path) -> None:
        """T-PL-12: Concurrent same-process start calls spawn exactly one child subprocess."""
        run_dir = tmp_path / "run" / "playit"
        supervisor = PlayitAgentSupervisor(run_dir=run_dir, health_interval=0.1)
        proc = _mock_subprocess()

        try:
            with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
                await asyncio.gather(
                    supervisor.start(secret=b"secret-1"),
                    supervisor.start(secret=b"secret-1"),
                    supervisor.start(secret=b"secret-1"),
                    supervisor.start(secret=b"secret-1"),
                    supervisor.start(secret=b"secret-1"),
                )
                assert supervisor.is_running is True
                assert mock_exec.call_count == 1
        finally:
            await supervisor.stop()

    async def test_callback_task_survives_gc_and_executes(self, tmp_path: Path) -> None:
        """ISS-018: Background task callbacks in PlayitSupervisor must not be garbage-collected."""
        import gc

        run_dir = tmp_path / "run" / "playit_gc"
        supervisor = PlayitAgentSupervisor(run_dir=run_dir)
        status_received = asyncio.Event()

        async def slow_on_status(_new_status: ExposureStatus) -> None:
            await asyncio.sleep(0.05)
            status_received.set()

        supervisor._on_status = slow_on_status
        supervisor._set_status(ExposureStatus.ACTIVE)

        # Ensure task is tracked in supervisor._background_tasks
        assert len(supervisor._background_tasks) > 0

        # Force aggressive GC while callback task is running
        gc.collect()
        gc.collect()

        await asyncio.wait_for(status_received.wait(), timeout=1.0)
        await asyncio.sleep(0.02)
        # Task done callback should have discarded it from the set
        assert len(supervisor._background_tasks) == 0
