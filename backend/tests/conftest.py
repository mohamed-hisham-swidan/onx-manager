import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.modules.activity.infrastructure.models  # noqa: F401
import app.modules.auth.infrastructure.models  # noqa: F401
import app.modules.backup.infrastructure.models  # noqa: F401
import app.modules.event_store.models  # noqa: F401
import app.modules.exposure.infrastructure.models  # noqa: F401
import app.modules.health.infrastructure.models  # noqa: F401
import app.modules.monitoring.infrastructure.models  # noqa: F401
import app.modules.plugin.infrastructure.models  # noqa: F401
import app.modules.server.infrastructure.models  # noqa: F401
import app.modules.versioning.infrastructure.models  # noqa: F401
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.exceptions import MCSError
from app.core.idempotency import InMemoryIdempotencyStore
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus


@pytest_asyncio.fixture(autouse=True)
async def _isolate_db_autouse(request: pytest.FixtureRequest) -> AsyncGenerator[None, None]:
    old_engine = database._engine
    old_factory = database._session_factory

    if request.node.get_closest_marker("no_isolated_db"):
        try:
            yield
        finally:
            database._engine = old_engine
            database._session_factory = old_factory
        return

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    database._engine = engine
    database._session_factory = factory

    try:
        yield
    finally:
        await engine.dispose()
        database._engine = old_engine
        database._session_factory = old_factory


@pytest_asyncio.fixture
async def init_test_db() -> AsyncGenerator[None, None]:
    """Compatibility fixture for tests requesting init_test_db explicitly."""
    yield


_ORIGINAL_OS_KILL = os.kill
_ORIGINAL_OS_KILLPG = getattr(os, "killpg", None)


def _is_descendant_pid(target_pid: int) -> bool:
    if not isinstance(target_pid, int) or target_pid <= 0:
        return False
    try:
        import psutil

        current_proc = psutil.Process()
        children = current_proc.children(recursive=True)
        return target_pid in {p.pid for p in children}
    except Exception:
        return False


def _is_descendant_pgid(target_pgid: int) -> bool:
    if not isinstance(target_pgid, int) or target_pgid <= 0:
        return False
    try:
        import psutil

        current_proc = psutil.Process()
        for p in current_proc.children(recursive=True):
            try:
                if os.getpgid(p.pid) == target_pgid or p.pid == target_pgid:
                    return True
            except OSError:
                pass
        return False
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _guard_real_signals(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermetic signal safety guard preventing tests from sending real signals to non-children.

    Behavior & Safety Notes:
    - Wraps `os.kill` and `os.killpg` during tests; allows signaling only if the target
      PID/PGID is a verified descendant of the current pytest process (via psutil).
    - If targeting an unrelated/non-child process, raises `AssertionError` (not `OSError`).
    - Note on LocalLinuxProvider: `LocalLinuxProvider._is_pid_alive` (local.py ~529-545)
      catches broad `Exception` and falls back to a real `kill -0` shell probe; tests
      exercising `LocalLinuxProvider` with simulated/fake PIDs must mock `_is_pid_alive`
      and/or `_run_command`/shell probes to prevent unhandled probe escapes.
    - Win32 residual: The `ctypes.windll.kernel32.TerminateProcess` path in `process_utils.py`
      (`platform_force_kill`) is platform-native on Windows and is not intercepted by this
      POSIX-focused `os.kill` wrapper.
    """
    if request.node.get_closest_marker("allow_real_signals"):
        return

    def safe_kill(pid: int, sig: int) -> None:
        if _is_descendant_pid(pid):
            return _ORIGINAL_OS_KILL(pid, sig)
        raise AssertionError(f"real os.kill({pid}, {sig}) blocked in tests")

    def safe_killpg(pgid: int, sig: int) -> None:
        if _is_descendant_pgid(pgid):
            if _ORIGINAL_OS_KILLPG is not None:
                return _ORIGINAL_OS_KILLPG(pgid, sig)
            return None
        raise AssertionError(f"real os.killpg({pgid}, {sig}) blocked in tests")

    monkeypatch.setattr(os, "kill", safe_kill)
    if hasattr(os, "killpg"):
        monkeypatch.setattr(os, "killpg", safe_killpg)


@pytest.fixture(autouse=True)
def _sandbox_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(backend_dir)


@pytest.fixture(autouse=True)
def _sandbox_servers_data_dir(tmp_path: os.PathLike) -> None:
    old_val = os.environ.get("MCS_SERVERS_DATA_DIR")
    test_servers_dir = os.path.join(str(tmp_path), "test_servers")
    os.makedirs(test_servers_dir, exist_ok=True)
    os.environ["MCS_SERVERS_DATA_DIR"] = test_servers_dir
    yield
    if old_val is not None:
        os.environ["MCS_SERVERS_DATA_DIR"] = old_val
    else:
        os.environ.pop("MCS_SERVERS_DATA_DIR", None)


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def command_bus() -> CommandBus:
    return CommandBus()


@pytest_asyncio.fixture
async def query_bus() -> QueryBus:
    return QueryBus()


@pytest_asyncio.fixture
async def event_bus() -> EventBus:
    return EventBus()


@pytest_asyncio.fixture
async def idempotency_store() -> InMemoryIdempotencyStore:
    return InMemoryIdempotencyStore()


class MockHandler:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.raise_error: type[MCSError] | None = None

    async def __call__(self, message: object) -> Any:
        self.calls.append(message)
        if self.raise_error:
            raise self.raise_error("mock error")
        return {"handled": True}


@pytest.fixture(autouse=True)
def _init_stub_task_queue() -> None:
    """Ensure get_task_queue() is always available in tests.

    Production initializes a real InProcessQueue at startup; the test
    environment does not, so the backup create handler would raise
    'TaskQueue not initialized'. A no-op stub keeps the success path green.
    """
    from app.tasks.base import TaskQueue, TaskStatus
    from app.tasks.queue import init_task_queue

    class StubTaskQueue(TaskQueue):
        async def enqueue(self, _name: str, _params: dict | None = None, _delay: int = 0) -> str:
            return "stub-task-id"

        async def cancel(self, _task_id: str) -> bool:
            return True

        async def get_status(self, _task_id: str) -> TaskStatus:
            return TaskStatus.PENDING

        async def get_result(self, _task_id: str) -> object:
            return None

    init_task_queue(StubTaskQueue())
    yield
    init_task_queue(StubTaskQueue())


@pytest.fixture
def mock_os_killpg():
    """Scoped mock for os.killpg that safely resolves on Windows where os.killpg does not exist."""
    from unittest.mock import patch

    with patch("os.killpg", create=True) as mock_killpg:
        yield mock_killpg
