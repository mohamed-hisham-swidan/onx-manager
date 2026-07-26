import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.exceptions import MCSError
from app.core.idempotency import InMemoryIdempotencyStore
from app.core.query_bus import QueryBus


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
