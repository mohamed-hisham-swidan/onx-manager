import pytest

from app.tasks.definitions.cleanup_task import run_cleanup_task


@pytest.mark.asyncio
async def test_cleanup_task_requires_db() -> None:
    with pytest.raises(Exception):
        await run_cleanup_task({})


@pytest.mark.asyncio
async def test_cleanup_task_with_params() -> None:
    with pytest.raises(Exception):
        await run_cleanup_task(
            {
                "cleanup_logs": True,
                "cleanup_idempotency": True,
                "cleanup_events": True,
                "cleanup_task_queue": True,
            }
        )


@pytest.mark.asyncio
async def test_event_cleanup_task_retention_days_vs_hours() -> None:
    from datetime import UTC, datetime, timedelta
    from unittest.mock import patch

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.persistence.base import Base
    from app.core.persistence.db import database
    from app.modules.event_store.models import StoredEventModel
    from app.tasks.definitions.event_cleanup import run_event_cleanup_task

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    now = datetime.now(UTC)
    async with session_factory() as s:
        # 1h old raw: keep (raw retention 2h)
        s.add(
            StoredEventModel(
                event_id="e1",
                event_type="metric.cpu",
                data_json="{}",
                hash="h1",
                created_at=now - timedelta(hours=1),
            )
        )
        # 3h old raw: purge (raw retention 2h)
        s.add(
            StoredEventModel(
                event_id="e2",
                event_type="metric.cpu",
                data_json="{}",
                hash="h2",
                created_at=now - timedelta(hours=3),
            )
        )
        # 2d old 1m rollup: keep under 30 days retention (would be purged under buggy 30 hours)
        s.add(
            StoredEventModel(
                event_id="e3",
                event_type="metric.1m_rollup.cpu",
                data_json="{}",
                hash="h3",
                created_at=now - timedelta(days=2),
            )
        )
        # 35d old 1m rollup: purge (older than 30 days retention)
        s.add(
            StoredEventModel(
                event_id="e4",
                event_type="metric.1m_rollup.cpu",
                data_json="{}",
                hash="h4",
                created_at=now - timedelta(days=35),
            )
        )
        await s.commit()

    with patch.object(database, "_session_factory", session_factory):
        results = await run_event_cleanup_task(
            {"raw_retention_hours": 2, "rollup_1m_retention_days": 30}
        )
        assert results["raw"] == 1
        assert results["1m_rollup"] == 1

    async with session_factory() as s:
        remaining = list((await s.execute(select(StoredEventModel))).scalars().all())
        remaining_ids = {r.event_id for r in remaining}
        assert remaining_ids == {"e1", "e3"}

    await engine.dispose()
