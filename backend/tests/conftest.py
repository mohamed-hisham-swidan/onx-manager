import asyncio
import os
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.exceptions import MCSError
from app.core.idempotency import InMemoryIdempotencyStore
from app.core.query_bus import QueryBus


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
