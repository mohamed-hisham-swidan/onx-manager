from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.persistence.base import Base
from app.modules.health.domain.aggregate import HealthStatus
from app.modules.health.domain.value_objects import (
    HealthStatusEnum,
    HealthTimelineEntry,
    HealthTrend,
)
from app.modules.health.infrastructure.repository import SQLHealthRepository

pytestmark = pytest.mark.asyncio

TEST_DB_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class TestSQLHealthRepository:
    async def test_save_and_get(self, db_session: AsyncSession) -> None:
        repo = SQLHealthRepository(db_session)
        status = HealthStatus.create("srv_test_1")

        await repo.save(status)
        await db_session.commit()

        loaded = await repo.get("srv_test_1")

        assert loaded is not None
        assert loaded.server_id == "srv_test_1"
        assert loaded.classification == HealthStatusEnum.PENDING

    async def test_save_and_get_with_update(self, db_session: AsyncSession) -> None:
        repo = SQLHealthRepository(db_session)
        status = HealthStatus.create("srv_test_2")
        await repo.save(status)
        await db_session.commit()

        status = await repo.get("srv_test_2")
        assert status is not None
        status.update(
            new_classification=HealthStatusEnum.HEALTHY,
            contributing_factors=["All checks passed"],
            trend=HealthTrend.IMPROVING,
            confidence=0.95,
        )
        await repo.save(status)
        await db_session.commit()

        loaded = await repo.get("srv_test_2")

        assert loaded is not None
        assert loaded.classification == HealthStatusEnum.HEALTHY
        assert loaded.contributing_factors == ["All checks passed"]
        assert loaded.trend == HealthTrend.IMPROVING
        assert loaded.confidence == 0.95

    async def test_get_nonexistent(self, db_session: AsyncSession) -> None:
        repo = SQLHealthRepository(db_session)
        result = await repo.get("nonexistent")
        assert result is None

    async def test_list_all(self, db_session: AsyncSession) -> None:
        repo = SQLHealthRepository(db_session)
        for i in range(3):
            status = HealthStatus.create(f"srv_list_{i}")
            await repo.save(status)
        await db_session.commit()

        all_statuses = await repo.list_all()

        assert len(all_statuses) == 3

    async def test_list_by_classification(self, db_session: AsyncSession) -> None:
        repo = SQLHealthRepository(db_session)
        s1 = HealthStatus.create("srv_cls_1")
        s1.update(HealthStatusEnum.HEALTHY)
        s2 = HealthStatus.create("srv_cls_2")
        s2.update(HealthStatusEnum.WARNING)
        s3 = HealthStatus.create("srv_cls_3")
        s3.update(HealthStatusEnum.HEALTHY)
        await repo.save(s1)
        await repo.save(s2)
        await repo.save(s3)
        await db_session.commit()

        healthy = await repo.list_by_classification("healthy")

        assert len(healthy) == 2
        assert all(s.classification == HealthStatusEnum.HEALTHY for s in healthy)

    async def test_append_and_get_timeline(self, db_session: AsyncSession) -> None:
        repo = SQLHealthRepository(db_session)
        entry1 = HealthTimelineEntry(
            server_id="srv_tl_1",
            previous_status=HealthStatusEnum.PENDING,
            new_status=HealthStatusEnum.HEALTHY,
            contributing_factors=["ok"],
        )
        entry2 = HealthTimelineEntry(
            server_id="srv_tl_1",
            previous_status=HealthStatusEnum.HEALTHY,
            new_status=HealthStatusEnum.WARNING,
            contributing_factors=["high cpu"],
        )
        await repo.append_timeline(entry1)
        await repo.append_timeline(entry2)
        await db_session.commit()

        entries = await repo.get_timeline("srv_tl_1", limit=10)

        assert len(entries) == 2
        assert entries[0].new_status == HealthStatusEnum.WARNING
        assert entries[0].previous_status == HealthStatusEnum.HEALTHY
        assert entries[1].new_status == HealthStatusEnum.HEALTHY

    async def test_timeline_with_since(self, db_session: AsyncSession) -> None:
        repo = SQLHealthRepository(db_session)
        entry = HealthTimelineEntry(
            server_id="srv_tl_2",
            previous_status=None,
            new_status=HealthStatusEnum.HEALTHY,
        )
        await repo.append_timeline(entry)
        await db_session.commit()

        future = datetime(2099, 1, 1, tzinfo=UTC)
        entries = await repo.get_timeline("srv_tl_2", limit=10, since=future)

        assert len(entries) == 0

    async def test_timeline_by_status(self, db_session: AsyncSession) -> None:
        repo = SQLHealthRepository(db_session)
        e1 = HealthTimelineEntry("srv_a", None, HealthStatusEnum.CRITICAL)
        e2 = HealthTimelineEntry("srv_b", None, HealthStatusEnum.HEALTHY)
        e3 = HealthTimelineEntry("srv_c", None, HealthStatusEnum.CRITICAL)
        await repo.append_timeline(e1)
        await repo.append_timeline(e2)
        await repo.append_timeline(e3)
        await db_session.commit()

        critical = await repo.get_timeline_by_status("critical", limit=10)

        assert len(critical) == 2
