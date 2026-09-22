from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from app.core.event_bus import EventBus


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()



@pytest_asyncio.fixture
async def event_bus() -> EventBus:
    return EventBus()
