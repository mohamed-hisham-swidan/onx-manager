"""P2-5b repo lease fencing, heartbeat, flock, and fail-closed wiring."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppSettings
from app.core.exceptions import FencingTokenMismatchError
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus
from app.modules.server.application.lifecycle_lock import ServerLifecycleLeaseManager
from app.modules.versioning.application.repo_lease import (
    RepoLeaseManager,
    RepoLeaseTimeoutError,
)
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.clean_export import (
    CleanExportRequest,
    CleanExportService,
)
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="P2 Advanced-mode repo leases are POSIX-only; Windows remains Simple-only",
)

SERVER_ID = "srv-lease"


def _build_db(tmp_path: Path) -> tuple[Path, object, sessionmaker[Session]]:
    db_path = tmp_path / "lease.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    result = DatabaseReconciler(db_url=db_url).reconcile(auto_upgrade=True)
    assert result.status == ReconcileStatus.RECONCILED, result.message
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return db_path, engine, factory


@pytest.fixture
def lease_env(tmp_path: Path):
    db_path, engine, factory = _build_db(tmp_path)
    try:
        yield db_path, engine, factory
    finally:
        engine.dispose()


def _manager(
    sync_factory: sessionmaker[Session],
    tmp_path: Path,
    *,
    ttl_seconds: float = 30.0,
    heartbeat_interval_seconds: float = 10.0,
    wait_timeout_seconds: float = 5.0,
    locks_dir: Path | None = None,
) -> RepoLeaseManager:
    return RepoLeaseManager(
        sync_session_factory=sync_factory,
        locks_dir=locks_dir or (tmp_path / "locks"),
        ttl_seconds=ttl_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        wait_timeout_seconds=wait_timeout_seconds,
    )


def _force_expiry(engine, server_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE server_repo_leases "
                "SET expires_at = '2000-01-01 00:00:00.000' "
                "WHERE server_id = :sid"
            ),
            {"sid": server_id},
        )


def _lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )


def _write(root: Path, relpath: str, data: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def _host(tmp_path: Path, server_id: str) -> tuple[HostStateLayout, Path, str]:
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    root = tmp_path / "servers" / server_id
    root.mkdir(parents=True)
    _write(root, "server.properties", "motd=Hello\n")
    result = GitRepositoryService(layout).initialize(server_id, root, _lockfile())
    return layout, root, result.main_sha


def _stale_token_error() -> None:
    raise FencingTokenMismatchError(
        server_id=SERVER_ID,
        expected_token=1,
        actual_token=99,
    )


def test_fencing_token_monotonic_across_release_and_reacquire(
    lease_env, tmp_path: Path
) -> None:
    _, _, factory = lease_env
    manager = _manager(factory, tmp_path)

    first = manager.try_acquire_sync(SERVER_ID, holder="a", ttl_seconds=30)
    assert first is not None and first.fencing_token == 1
    assert manager.try_acquire_sync(SERVER_ID, holder="b", ttl_seconds=30) is None
    assert manager.release_sync(first) is True

    second = manager.try_acquire_sync(SERVER_ID, holder="b", ttl_seconds=30)
    assert second is not None and second.fencing_token == 2
    assert manager.release_sync(second) is True

    third = manager.try_acquire_sync(SERVER_ID, holder="c", ttl_seconds=30)
    assert third is not None and third.fencing_token == 3
    assert manager.release_sync(third) is True


def test_fencing_token_increments_after_expiry(lease_env, tmp_path: Path) -> None:
    _, engine, factory = lease_env
    manager = _manager(factory, tmp_path)

    first = manager.try_acquire_sync(SERVER_ID, holder="a", ttl_seconds=30)
    assert first is not None and first.fencing_token == 1
    _force_expiry(engine, SERVER_ID)

    second = manager.try_acquire_sync(SERVER_ID, holder="b", ttl_seconds=30)
    assert second is not None and second.fencing_token == 2
    assert second.holder == "b"


def test_assert_fencing_token_rejects_stale_released_and_expired(
    lease_env, tmp_path: Path
) -> None:
    _, engine, factory = lease_env
    manager = _manager(factory, tmp_path)

    holder = manager.try_acquire_sync(SERVER_ID, holder="a", ttl_seconds=30)
    assert holder is not None

    with pytest.raises(FencingTokenMismatchError) as stale:
        manager.assert_fencing_token_sync(SERVER_ID, holder.fencing_token + 10)
    assert stale.value.http_status == 409
    assert stale.value.code == "FENCING_TOKEN_MISMATCH"
    assert stale.value.details["expected_token"] == holder.fencing_token + 10

    manager.assert_fencing_token_sync(SERVER_ID, holder.fencing_token)
    assert manager.release_sync(holder) is True
    with pytest.raises(FencingTokenMismatchError):
        manager.assert_fencing_token_sync(SERVER_ID, holder.fencing_token)

    expired = manager.try_acquire_sync(SERVER_ID, holder="b", ttl_seconds=30)
    assert expired is not None and expired.fencing_token == 2
    _force_expiry(engine, SERVER_ID)
    with pytest.raises(FencingTokenMismatchError):
        manager.assert_fencing_token_sync(SERVER_ID, expired.fencing_token)


def test_heartbeat_keeps_lease_alive(lease_env, tmp_path: Path) -> None:
    _, _, factory = lease_env
    manager = _manager(
        factory,
        tmp_path,
        ttl_seconds=0.35,
        heartbeat_interval_seconds=0.1,
    )

    with manager.acquire_sync(SERVER_ID, holder="hb", ttl_seconds=0.35) as token:
        time.sleep(0.6)
        assert token.is_lost is False
        manager.assert_fencing_token_sync(SERVER_ID, token.fencing_token)

    with pytest.raises(FencingTokenMismatchError):
        manager.assert_fencing_token_sync(SERVER_ID, token.fencing_token)


def test_flock_serializes_threads(lease_env, tmp_path: Path) -> None:
    _, _, factory = lease_env
    first = _manager(factory, tmp_path)
    second = _manager(factory, tmp_path)
    order: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    def worker(manager: RepoLeaseManager, name: str) -> None:
        with manager.acquire_sync(
            SERVER_ID, holder=name, wait_timeout=5.0, ttl_seconds=10.0
        ):
            order.append(f"{name}-enter")
            if name == "a":
                entered.set()
                release.wait(5.0)
            order.append(f"{name}-exit")

    thread_a = threading.Thread(target=worker, args=(first, "a"))
    thread_a.start()
    assert entered.wait(5.0)
    thread_b = threading.Thread(target=worker, args=(second, "b"))
    thread_b.start()
    time.sleep(0.2)
    assert order == ["a-enter"]
    release.set()
    thread_a.join(5.0)
    thread_b.join(5.0)
    assert order == ["a-enter", "a-exit", "b-enter", "b-exit"]


def test_flock_timeout_raises_repo_lease_timeout(lease_env, tmp_path: Path) -> None:
    _, _, factory = lease_env
    first = _manager(factory, tmp_path)
    second = _manager(factory, tmp_path)

    with (
        first.acquire_sync(SERVER_ID, holder="a", ttl_seconds=10.0),
        pytest.raises(RepoLeaseTimeoutError) as timeout,
        second.acquire_sync(
            SERVER_ID, holder="b", wait_timeout=0.1, ttl_seconds=10.0
        ),
    ):
        pass
    assert timeout.value.http_status == 409
    assert timeout.value.code == "REPO_LEASE_TIMEOUT"


def test_async_try_acquire_and_assert(lease_env) -> None:
    db_path, _, sync_factory = lease_env

    async def scenario() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        manager = RepoLeaseManager(
            sync_session_factory=sync_factory,
            session_factory=async_factory,
            ttl_seconds=30.0,
        )
        try:
            first = await manager.try_acquire(SERVER_ID, holder="a", ttl_seconds=30)
            assert first is not None and first.fencing_token == 1
            assert await manager.try_acquire(SERVER_ID, holder="b") is None
            await manager.assert_fencing_token(SERVER_ID, first.fencing_token)
            assert await manager.release(first) is True
            with pytest.raises(FencingTokenMismatchError):
                await manager.assert_fencing_token(SERVER_ID, first.fencing_token)
            second = await manager.try_acquire(SERVER_ID, holder="b", ttl_seconds=30)
            assert second is not None and second.fencing_token == 2
            assert await manager.release(second) is True
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_lock_order_rejects_lifecycle_after_repo(lease_env, tmp_path: Path) -> None:
    db_path, _, sync_factory = lease_env

    async def scenario() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        manager = RepoLeaseManager(
            sync_session_factory=sync_factory,
            session_factory=async_factory,
            locks_dir=tmp_path / "locks",
            ttl_seconds=30.0,
        )
        lifecycle = ServerLifecycleLeaseManager(session_factory=async_factory)
        try:
            async with manager.acquire(
                SERVER_ID, holder="repo", wait_timeout=2.0, ttl_seconds=10.0
            ):
                with pytest.raises(RuntimeError, match="Lock order violation"):
                    async with lifecycle.acquire(
                        SERVER_ID, holder="lifecycle", wait_timeout=0
                    ):
                        pass
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_clean_export_fails_closed_on_stale_fencing_token(
    tmp_path: Path,
) -> None:
    layout, root, sha = _host(tmp_path, SERVER_ID)
    request = CleanExportRequest(
        server_id=SERVER_ID,
        server_root=root,
        commit_sha=sha,
        destination=tmp_path / "export",
        lockfile=_lockfile(),
    )

    with pytest.raises(FencingTokenMismatchError):
        CleanExportService(layout).export(request, fencing_verifier=_stale_token_error)

    assert not (tmp_path / "export").exists()


def test_git_branch_mutations_fail_closed_on_stale_fencing_token(
    tmp_path: Path,
) -> None:
    layout, root, _ = _host(tmp_path, SERVER_ID)
    service = GitBranchService(layout)

    with pytest.raises(FencingTokenMismatchError):
        service.create_branch(
            SERVER_ID, root, "feature/x", fencing_verifier=_stale_token_error
        )
    assert service.get_branch(SERVER_ID, root, "feature/x") is None

    service.create_branch(SERVER_ID, root, "kept")
    with pytest.raises(FencingTokenMismatchError):
        service.archive_branch(
            SERVER_ID, root, "kept", fencing_verifier=_stale_token_error
        )
    assert service.get_branch(SERVER_ID, root, "kept") is not None

    service.create_branch(SERVER_ID, root, "to-delete")
    with pytest.raises(FencingTokenMismatchError):
        service.delete_branch(
            SERVER_ID, root, "to-delete", fencing_verifier=_stale_token_error
        )
    assert service.get_branch(SERVER_ID, root, "to-delete") is not None
