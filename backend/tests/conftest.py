import asyncio
import os
from collections.abc import AsyncGenerator
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
