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
