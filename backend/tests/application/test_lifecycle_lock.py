from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.command_bus import Command, CommandBus, CommandHandler, CommandResult
from app.core.persistence.db import database
from app.modules.server.application.lifecycle_lock import (
    LeaseToken,
    ServerLifecycleLeaseManager,
    ServerLifecycleLockMiddleware,
    ServerLifecycleLockTimeoutError,
)


class DummyLifecycleCommand(Command):
    server_id: str


class DummyStartCommand(Command):
    server_id: str


class TestLifecycleLock:
    @pytest.mark.asyncio
    async def test_acquire_and_release(self) -> None:
        mgr = ServerLifecycleLeaseManager(database.session_factory)
        sid = "srv-lease-1"

        async with mgr.acquire(sid, holder="test_acquire", wait_timeout=5.0) as token:
            assert isinstance(token, LeaseToken)
            assert token.server_id == sid
            assert token.holder == "test_acquire"
            assert not token.reentrant

            # Row exists in DB
            async with database.session_factory() as session:
                res = await session.execute(
                    text(
                        "SELECT holder, owner_token FROM server_lifecycle_leases "
                        "WHERE server_id = :sid"
                    ),
                    {"sid": sid},
                )
                row = res.fetchone()
                assert row is not None
                assert row[0] == "test_acquire"
                assert row[1] == token.owner_token

        # Released
        async with database.session_factory() as session:
            res = await session.execute(
                text(
                    "SELECT holder, owner_token FROM server_lifecycle_leases "
                    "WHERE server_id = :sid"
                ),
                {"sid": sid},
            )
            row = res.fetchone()
            assert row is not None
            assert row[0] is None
            assert row[1] is None

    @pytest.mark.asyncio
    async def test_concurrent_acquire_blocks_until_released(self) -> None:
        mgr = ServerLifecycleLeaseManager(database.session_factory)
        sid = "srv-lease-concurrent"
        order: list[str] = []

        async def worker_1():
            async with mgr.acquire(sid, holder="worker_1", wait_timeout=5.0):
                order.append("w1_acquired")
                await asyncio.sleep(0.3)
                order.append("w1_releasing")

        async def worker_2():
            await asyncio.sleep(0.05)
            async with mgr.acquire(sid, holder="worker_2", wait_timeout=5.0):
                order.append("w2_acquired")

        await asyncio.gather(worker_1(), worker_2())
        assert order == ["w1_acquired", "w1_releasing", "w2_acquired"]

    @pytest.mark.asyncio
    async def test_expired_lease_is_stolen(self) -> None:
        mgr = ServerLifecycleLeaseManager(database.session_factory)
        sid = "srv-lease-expired"
        past = datetime.now(UTC) - timedelta(seconds=100)

        # Seed expired lease in DB
        async with database.session_factory() as session:
            conn = await session.connection()
            if conn.dialect.name == "sqlite":
                await session.execute(
                    text(
                        "INSERT OR IGNORE INTO server_lifecycle_leases "
                        "(server_id, updated_at) VALUES (:sid, :now)"
                    ),
                    {"sid": sid, "now": past},
                )
            else:
                await session.execute(
                    text(
                        "INSERT INTO server_lifecycle_leases "
                        "(server_id, updated_at) VALUES (:sid, :now) ON CONFLICT DO NOTHING"
                    ),
                    {"sid": sid, "now": past},
                )
            await session.execute(
                text(
                    "UPDATE server_lifecycle_leases "
                    "SET holder = 'old_dead_worker', owner_token = 'stale-token', "
                    "acquired_at = :past, expires_at = :past, updated_at = :past "
                    "WHERE server_id = :sid"
                ),
                {"sid": sid, "past": past},
            )
            await session.commit()

        # New worker should acquire immediately
        token = await mgr.try_acquire(sid, holder="new_worker", ttl_seconds=60.0)
        assert token is not None
        assert token.holder == "new_worker"
        assert token.owner_token != "stale-token"

        # Stale owner releasing does NOT clear new worker's lease
        stale_token = LeaseToken(
            server_id=sid, owner_token="stale-token", holder="old_dead_worker"
        )
        released = await mgr.release(stale_token)
        assert released is False

        # Verify new worker's lease is still intact
        async with database.session_factory() as session:
            res = await session.execute(
                text(
                    "SELECT holder, owner_token FROM server_lifecycle_leases "
                    "WHERE server_id = :sid"
                ),
                {"sid": sid},
            )
            row = res.fetchone()
            assert row[0] == "new_worker"
            assert row[1] == token.owner_token

        # Clean up
        await mgr.release(token)

    @pytest.mark.asyncio
    async def test_wait_timeout_raises_timeout_error(self) -> None:
        mgr = ServerLifecycleLeaseManager(database.session_factory)
        sid = "srv-lease-timeout"

        token = await mgr.try_acquire(sid, holder="blocker", ttl_seconds=60.0)
        assert token is not None

        try:
            with pytest.raises(ServerLifecycleLockTimeoutError) as exc_info:
                async with mgr.acquire(sid, holder="waiter", wait_timeout=0.2):
                    pass
            assert exc_info.value.server_id == sid
        finally:
            await mgr.release(token)

    @pytest.mark.asyncio
    async def test_contextvar_same_task_reentrancy(self) -> None:
        mgr = ServerLifecycleLeaseManager(database.session_factory)
        sid = "srv-lease-reentrant"

        async with mgr.acquire(sid, holder="outer", wait_timeout=5.0) as outer_token:
            assert not outer_token.reentrant

            # Nested acquire for same server_id inside same async task
            async with mgr.acquire(sid, holder="inner", wait_timeout=5.0) as inner_token:
                assert inner_token.reentrant
                assert inner_token.owner_token == outer_token.owner_token

            # Exiting inner scope did not release outer DB lease
            async with database.session_factory() as session:
                res = await session.execute(
                    text("SELECT owner_token FROM server_lifecycle_leases WHERE server_id = :sid"),
                    {"sid": sid},
                )
                assert res.scalar_one_or_none() == outer_token.owner_token

        # Exiting outer scope releases DB lease
        async with database.session_factory() as session:
            res = await session.execute(
                text("SELECT owner_token FROM server_lifecycle_leases WHERE server_id = :sid"),
                {"sid": sid},
            )
            assert res.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_exception_in_handler_releases_lease(self) -> None:
        mgr = ServerLifecycleLeaseManager(database.session_factory)
        sid = "srv-lease-exc"

        with pytest.raises(RuntimeError, match="boom"):
            async with mgr.acquire(sid, holder="crashing_task", wait_timeout=5.0):
                raise RuntimeError("boom")

        # Lease should be released
        async with database.session_factory() as session:
            res = await session.execute(
                text("SELECT owner_token FROM server_lifecycle_leases WHERE server_id = :sid"),
                {"sid": sid},
            )
            assert res.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_cancellation_releases_lease(self) -> None:
        mgr = ServerLifecycleLeaseManager(database.session_factory)
        sid = "srv-lease-cancel"
        acquired_event = asyncio.Event()

        async def worker():
            async with mgr.acquire(sid, holder="cancelled_task", wait_timeout=5.0):
                acquired_event.set()
                await asyncio.sleep(10.0)

        task = asyncio.create_task(worker())
        await acquired_event.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Lease should be released
        async with database.session_factory() as session:
            res = await session.execute(
                text("SELECT owner_token FROM server_lifecycle_leases WHERE server_id = :sid"),
                {"sid": sid},
            )
            assert res.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_middleware_concurrency_conflict(self) -> None:
        from app.modules.server.application.commands.start_server import StartServerCommand

        mgr = ServerLifecycleLeaseManager(database.session_factory)
        sid = "srv-middleware-conflict"

        # Manually hold lease
        token = await mgr.try_acquire(sid, holder="external_lock", ttl_seconds=60.0)
        assert token is not None

        try:
            bus = CommandBus()
            bus.add_middleware(ServerLifecycleLockMiddleware(mgr))

            class FakeStartHandler(CommandHandler[StartServerCommand]):
                async def handle(self, _cmd: StartServerCommand) -> CommandResult:
                    return CommandResult(success=True)

            bus.register(StartServerCommand, FakeStartHandler())

            # Monkeypatch timeout on mgr for fast test
            orig_acquire = mgr.acquire

            def fast_acquire(server_id, **kwargs):
                kwargs["wait_timeout"] = 0.1
                return orig_acquire(server_id, **kwargs)

            mgr.acquire = fast_acquire  # type: ignore[assignment]

            cmd = StartServerCommand(server_id=sid)
            result = await bus.send(cmd)

            assert result.success is False
            assert result.error_code == "OPERATION_CONCURRENCY_CONFLICT"
            assert "Another lifecycle operation is already in progress" in (result.error or "")
        finally:
            await mgr.release(token)

    @pytest.mark.asyncio
    async def test_heartbeat_transient_failure_retries_and_keeps_lease(self) -> None:
        mgr = ServerLifecycleLeaseManager(database.session_factory)
        sid = "srv-transient-renew"

        token = await mgr.try_acquire(sid, holder="worker_transient", ttl_seconds=60.0)
        assert token is not None
        assert not getattr(token, "is_lost", False)

        attempts = 0

        async def flaky_renew(_tok: LeaseToken, _ttl: float) -> bool:
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                # Fail first 2 attempts
                return False
            return True

        mgr._renew = flaky_renew  # type: ignore[assignment]

        task = asyncio.create_task(
            mgr._heartbeat_loop(token, ttl_seconds=60.0, interval_seconds=0.01)
        )
        try:
            # Let heartbeat run through failures and recover
            await asyncio.sleep(0.25)
            assert getattr(token, "is_lost", False) is False
            assert attempts >= 3
            # Loop should still be active
            assert not task.done()
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await mgr.release(token)

    @pytest.mark.asyncio
    async def test_heartbeat_persistent_failure_marks_lease_lost(self) -> None:
        mgr = ServerLifecycleLeaseManager(database.session_factory)
        sid = "srv-persistent-fail"

        token = await mgr.try_acquire(sid, holder="worker_persistent", ttl_seconds=60.0)
        assert token is not None

        renew_calls = 0

        async def always_fail_renew(_tok: LeaseToken, _ttl: float) -> bool:
            nonlocal renew_calls
            renew_calls += 1
            return False

        mgr._renew = always_fail_renew  # type: ignore[assignment]

        with pytest.MonkeyPatch.context() as _mp:
            task = asyncio.create_task(
                mgr._heartbeat_loop(token, ttl_seconds=60.0, interval_seconds=0.01)
            )
            # Wait for 1 initial + 3 retries (total 4 attempts) and loop termination
            await asyncio.wait_for(task, timeout=2.0)

            assert renew_calls == 4
            assert getattr(token, "is_lost", False) is True

        await mgr.release(token)

    @pytest.mark.asyncio
    async def test_middleware_fails_closed_when_lease_lost_during_execution(self) -> None:
        from app.modules.server.application.commands.start_server import StartServerCommand

        mgr = ServerLifecycleLeaseManager(database.session_factory)
        sid = "srv-lease-lost-mid"

        bus = CommandBus()
        bus.add_middleware(ServerLifecycleLockMiddleware(mgr))

        active_token: LeaseToken | None = None
        orig_acquire = mgr.acquire

        @asynccontextmanager
        async def tracking_acquire(server_id, **kwargs):
            nonlocal active_token
            async with orig_acquire(server_id, **kwargs) as tok:
                active_token = tok
                yield tok

        mgr.acquire = tracking_acquire  # type: ignore[assignment]

        class DelayedHandler(CommandHandler[StartServerCommand]):
            async def handle(self, _cmd: StartServerCommand) -> CommandResult:
                assert active_token is not None
                active_token.is_lost = True
                return CommandResult(success=True)

        bus.register(StartServerCommand, DelayedHandler())
        cmd = StartServerCommand(server_id=sid)
        result = await bus.send(cmd)

        assert result.success is False
        assert result.error_code == "OPERATION_CONCURRENCY_CONFLICT"
        assert "Lifecycle lock was lost" in (result.error or "")

