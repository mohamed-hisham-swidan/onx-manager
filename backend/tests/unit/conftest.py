from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.modules.auth.infrastructure.models  # noqa: F401
import app.modules.server.infrastructure.models  # noqa: F401
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database

TEST_DB_URL = "sqlite+aiosqlite://"


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def init_test_db(tmp_path) -> AsyncGenerator[None, None]:
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    database._engine = engine
    database._session_factory = factory

    old_data_dir = os.environ.get("MCS_SERVERS_DATA_DIR")
    test_servers_dir = tmp_path / "test_servers"
    test_servers_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MCS_SERVERS_DATA_DIR"] = str(test_servers_dir)
    yield
    if old_data_dir is not None:
        os.environ["MCS_SERVERS_DATA_DIR"] = old_data_dir
    else:
        os.environ.pop("MCS_SERVERS_DATA_DIR", None)
    await engine.dispose()
    database._engine = None
    database._session_factory = None


@pytest_asyncio.fixture
async def event_bus() -> EventBus:
    return EventBus()
