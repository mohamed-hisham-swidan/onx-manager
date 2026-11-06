from __future__ import annotations

import time

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.activity.domain.entities import ServerActivityLog
from app.modules.activity.infrastructure.repository import SQLActivityRepository


@pytest.fixture
async def async_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine = database._engine
    old_factory = database._session_factory
    database._engine = engine
    database._session_factory = session_factory

    yield session_factory

    database._engine = old_engine
    database._session_factory = old_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_save_and_list_activity(async_db):
    repo = SQLActivityRepository(session_factory=async_db)

    now = time.time()
    log1 = ServerActivityLog(
        server_id="srv-1",
        event_type="server.started",
        summary="Server started successfully",
        timestamp=now - 100,
        actor_type="user",
        actor_id="user-123",
        details={"port": 25565},
    )
    log2 = ServerActivityLog(
        server_id="srv-1",
        event_type="server.stopped",
        summary="Server stopped",
        timestamp=now - 50,
        actor_type="system",
        actor_id=None,
        details={},
    )
    log_other = ServerActivityLog(
        server_id="srv-2",
        event_type="server.started",
        summary="Other server started",
        timestamp=now - 20,
    )

    await repo.save(log1)
    await repo.save(log2)
    await repo.save(log_other)

    items, total = await repo.list_by_server("srv-1", limit=10, offset=0)
    assert total == 2
    assert len(items) == 2
    # Order should be descending by timestamp (newest first: log2, then log1)
    assert items[0].id == log2.id
    assert items[0].summary == "Server stopped"
    assert items[1].id == log1.id
    assert items[1].actor_id == "user-123"
    assert items[1].details == {"port": 25565}


@pytest.mark.asyncio
async def test_activity_pagination_and_filters(async_db):
    repo = SQLActivityRepository(session_factory=async_db)
    base_time = 1000.0

    for i in range(10):
        ev_type = "plugin.installed" if i % 2 == 0 else "server.config_changed"
        await repo.save(
            ServerActivityLog(
                server_id="srv-filter",
                event_type=ev_type,
                summary=f"Action {i}",
                timestamp=base_time + (i * 10),
            )
        )

    # Test limit and offset
    page1, total = await repo.list_by_server("srv-filter", limit=4, offset=0)
    assert total == 10
    assert len(page1) == 4
    assert page1[0].summary == "Action 9"  # highest timestamp

    page2, _ = await repo.list_by_server("srv-filter", limit=4, offset=4)
    assert len(page2) == 4
    assert page2[0].summary == "Action 5"

    # Filter by event_type
    plugins, p_total = await repo.list_by_server(
        "srv-filter", event_type="plugin.installed"
    )
    assert p_total == 5
    assert len(plugins) == 5
    for p in plugins:
        assert p.event_type == "plugin.installed"

    # Filter by timestamp range
    range_items, r_total = await repo.list_by_server(
        "srv-filter",
        from_date=base_time + 25,
        to_date=base_time + 75,
    )
    # Timestamps in range: 30, 40, 50, 60, 70 (5 items)
    assert r_total == 5
    assert len(range_items) == 5


@pytest.mark.asyncio
async def test_delete_older_than(async_db):
    repo = SQLActivityRepository(session_factory=async_db)
    now = 10000.0

    await repo.save(
        ServerActivityLog(
            server_id="srv-del",
            event_type="test",
            summary="Old item 1",
            timestamp=now - 500,
        )
    )
    await repo.save(
        ServerActivityLog(
            server_id="srv-del",
            event_type="test",
            summary="Old item 2",
            timestamp=now - 200,
        )
    )
    await repo.save(
        ServerActivityLog(
            server_id="srv-del",
            event_type="test",
            summary="New item",
            timestamp=now - 50,
        )
    )

    deleted = await repo.delete_older_than(cutoff_timestamp=now - 100)
    assert deleted == 2

    remaining, total = await repo.list_by_server("srv-del")
    assert total == 1
    assert remaining[0].summary == "New item"


@pytest.mark.asyncio
async def test_save_with_shared_session_rolls_back_on_retry(async_db):
    async with async_db() as session:
        repo = SQLActivityRepository(session=session)
        real_commit = session.commit
        calls = 0

        async def _failing_commit():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise Exception("database is locked")
            return await real_commit()

        session.commit = _failing_commit
        log = ServerActivityLog(
            server_id="srv-retry",
            event_type="test",
            summary="Retry test",
            timestamp=100.0,
        )
        await repo.save(log, max_retries=2)
        assert calls == 2

        items, total = await repo.list_by_server("srv-retry")
        assert total == 1
        assert items[0].summary == "Retry test"
