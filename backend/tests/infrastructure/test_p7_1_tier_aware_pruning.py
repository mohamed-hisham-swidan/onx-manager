"""P7-1: Tier-aware pruning — FIFO=5 for tier_1, 7d/4w for tier_2, pinned exempt."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.backup.domain.aggregate import BackupJob, BackupType
from app.modules.backup.infrastructure.models import BackupJobModel
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId, ServerId


@pytest.fixture
async def app_db():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    yield
    await engine.dispose()
    database._engine = None
    database._session_factory = None


def _make_job(backup_id: str, server_id: str, tier: str, pinned: bool = False):
    return BackupJob.create(
        backup_id=BackupJobId(backup_id),
        server_id=ServerId(server_id),
        backup_type=BackupType.FULL,
        pinned=pinned,
        tier=tier,
    )


async def _save_job(session: AsyncSession, job, days_ago: int = 0):
    repo = SQLBackupRepository(session)
    await repo.save_job(job)
    created = datetime.now(UTC) - timedelta(days=days_ago)
    await session.execute(
        update(BackupJobModel)
        .where(BackupJobModel.id == str(job.backup_id))
        .values(created_at=created)
    )
    await session.flush()


@pytest.mark.asyncio
async def test_tier_1_fifo_five_unpinned(app_db):  # noqa: ARG001
    """F007: Tier-1 keeps only the last 5 unpinned snapshots (FIFO=5)."""
    async with database.session_factory() as session:
        repo = SQLBackupRepository(session)
        server = ServerId("srv-tier1")
        for i in range(7):
            job = _make_job(f"b1-{i:02d}", "srv-tier1", "tier_1")
            await _save_job(session, job, days_ago=7 - i)
        await session.commit()

        deleted = await repo.prune_old_backups(server, max_backups=5)
        assert len(deleted) == 2
        assert "b1-00" in deleted and "b1-01" in deleted

        survivors = await repo.list_jobs(server)
        assert len(survivors) == 5
        survivor_ids = {j.backup_id.value for j in survivors}
        assert survivor_ids == {f"b1-{i:02d}" for i in range(2, 7)}


@pytest.mark.asyncio
async def test_tier_1_pinned_exempt_from_fifo(app_db):  # noqa: ARG001
    """F008: Tier-1 pinned snapshots are never auto-pruned."""
    async with database.session_factory() as session:
        repo = SQLBackupRepository(session)
        server = ServerId("srv-tier1-pinned")
        for i in range(6):
            job = _make_job(
                f"bp-{i:02d}", "srv-tier1-pinned", "tier_1", pinned=(i == 5)
            )
            await _save_job(session, job, days_ago=6 - i)
        await session.commit()

        deleted = await repo.prune_old_backups(server, max_backups=5)
        assert deleted == []

        job7 = _make_job("bp-06", "srv-tier1-pinned", "tier_1")
        await _save_job(session, job7, days_ago=0)
        await session.commit()

        deleted = await repo.prune_old_backups(server, max_backups=5)
        assert "bp-00" in deleted
        assert "bp-05" not in deleted


@pytest.mark.asyncio
async def test_tier_2_7d_retention(app_db):  # noqa: ARG001
    """F009: Tier-2 prunes snapshots older than retention_days (default 7 days)."""
    async with database.session_factory() as session:
        repo = SQLBackupRepository(session)
        server = ServerId("srv-tier2")
        await _save_job(session, _make_job("b2-old", "srv-tier2", "tier_2"), days_ago=10)
        await _save_job(session, _make_job("b2-mid", "srv-tier2", "tier_2"), days_ago=3)
        await _save_job(session, _make_job("b2-new", "srv-tier2", "tier_2"), days_ago=1)
        await session.commit()

        deleted = await repo.prune_old_backups(
            server, retention_days=7, now=datetime.now(UTC)
        )
        assert "b2-old" in deleted
        assert "b2-mid" not in deleted
        assert "b2-new" not in deleted


@pytest.mark.asyncio
async def test_tier_2_pinned_exempt_from_retention(app_db):  # noqa: ARG001
    """F010: Tier-2 pinned snapshots are exempt from retention pruning."""
    async with database.session_factory() as session:
        repo = SQLBackupRepository(session)
        server = ServerId("srv-tier2-pinned")
        await _save_job(
            session,
            _make_job("b2p-old", "srv-tier2-pinned", "tier_2", pinned=True),
            days_ago=30,
        )
        await _save_job(session, _make_job("b2p-new", "srv-tier2-pinned", "tier_2"), days_ago=1)
        await session.commit()

        deleted = await repo.prune_old_backups(
            server, retention_days=7, now=datetime.now(UTC)
        )
        assert deleted == []


@pytest.mark.asyncio
async def test_tier_2_weekly_retention_max_4(app_db):  # noqa: ARG001
    """F011: Tier-2 keeps at most 4 weekly snapshots (one per ISO week)."""
    async with database.session_factory() as session:
        repo = SQLBackupRepository(session)
        server = ServerId("srv-tier2-weekly")
        base = datetime.now(UTC)
        for i in range(6):
            days_back = i * 7
            job = _make_job(f"bw-{i:02d}", "srv-tier2-weekly", "tier_2")
            created = base - timedelta(days=days_back)
            await repo.save_job(job)
            await session.execute(
                update(BackupJobModel)
                .where(BackupJobModel.id == str(job.backup_id))
                .values(created_at=created)
            )
        await session.commit()

        deleted = await repo.prune_old_backups(
            server, retention_days=60, now=base
        )
        assert len(deleted) == 2
