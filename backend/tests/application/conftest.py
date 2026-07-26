import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.query_bus import QueryBus
from app.storage.base import Base
from app.storage.db import database


TEST_DB_URL = "sqlite+aiosqlite://"


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def init_test_db() -> AsyncGenerator[None, None]:
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    database._engine = engine
    database._session_factory = factory
    yield
    await engine.dispose()
    database._engine = None
    database._session_factory = None


@pytest_asyncio.fixture
async def event_bus() -> EventBus:
    return EventBus()


@pytest_asyncio.fixture
async def command_bus() -> CommandBus:
    return CommandBus()


@pytest_asyncio.fixture
async def query_bus() -> QueryBus:
    return QueryBus()
