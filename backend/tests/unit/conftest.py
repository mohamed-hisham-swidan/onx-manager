from __future__ import annotations

import pytest_asyncio

from app.core.event_bus import EventBus


@pytest_asyncio.fixture
async def event_bus() -> EventBus:
    return EventBus()
