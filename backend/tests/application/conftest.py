import asyncio

import pytest
import pytest_asyncio

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.query_bus import QueryBus


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()



@pytest_asyncio.fixture
async def event_bus() -> EventBus:
    return EventBus()


@pytest_asyncio.fixture
async def command_bus() -> CommandBus:
    return CommandBus()


@pytest_asyncio.fixture
async def query_bus() -> QueryBus:
    return QueryBus()
