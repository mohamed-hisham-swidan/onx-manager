from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.persistence.base import Base
from app.modules.backup.domain.aggregate import BackupJob, BackupTier, BackupType
from app.modules.backup.infrastructure.models import BackupJobModel
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId, ServerId


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_job(
    repo: SQLBackupRepository,
    session,
    *,
    backup_id: str,
    server_id: str = "srv-1",
    tier: BackupTier,
    created_at: datetime,
    pinned: bool = False,
) -> None:
    job = BackupJob(
        backup_id=BackupJobId(backup_id),
        server_id=ServerId(server_id),
        backup_type=BackupType.FULL,
        created_at=created_at,
        pinned=pinned,
        tier=tier,
    )
    job.mark_completed(size_bytes=100, checksum="abc", storage_path=f"/tmp/{backup_id}")
    await repo.save_job(job)
    await session.execute(
        update(BackupJobModel)
        .where(BackupJobModel.id == backup_id)
        .values(created_at=created_at)
    )


@pytest.mark.asyncio
async def test_tier1_fifo_5_and_pinned_exempt_isolated_from_tier2(session_factory) -> None:
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    async with session_factory() as session:
        repo = SQLBackupRepository(session)
        # 6 unpinned Tier-1 + 1 pinned Tier-1 + 1 Tier-2
        for i in range(6):
            await _seed_job(
                repo,
                session,
                backup_id=f"t1-{i}",
                tier=BackupTier.TIER_1,
                created_at=now - timedelta(hours=6 - i),
            )
        await _seed_job(
            repo,
            session,
            backup_id="t1-pinned",
            tier=BackupTier.TIER_1,
            created_at=now - timedelta(days=10),
            pinned=True,
        )
        await _seed_job(
            repo,
            session,
            backup_id="t2-keep",
            tier=BackupTier.TIER_2,
            created_at=now - timedelta(days=20),
        )
        await session.commit()

        pruned = await repo.prune_old_backups(
            ServerId("srv-1"), tier=BackupTier.TIER_1, tier1_keep=5, now=now
        )
        await session.commit()

        assert pruned == ["t1-0"]
        t1_remaining = {j.backup_id.value for j in await repo.list_jobs(ServerId("srv-1"), tier=BackupTier.TIER_1)}
        assert t1_remaining == {"t1-1", "t1-2", "t1-3", "t1-4", "t1-5", "t1-pinned"}
        t2_remaining = {j.backup_id.value for j in await repo.list_jobs(ServerId("srv-1"), tier=BackupTier.TIER_2)}
        assert t2_remaining == {"t2-keep"}


@pytest.mark.asyncio
async def test_tier2_7_daily_union_4_weekly_and_pinned_exempt(session_factory) -> None:
    # Friday 2026-11-20 12:00 UTC
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    async with session_factory() as session:
        repo = SQLBackupRepository(session)
        # Two backups today -> keep only newest
        await _seed_job(repo, session, backup_id="d0-old", tier=BackupTier.TIER_2, created_at=now - timedelta(hours=3))
        await _seed_job(repo, session, backup_id="d0-new", tier=BackupTier.TIER_2, created_at=now)
        # 1 backup 3 days ago (inside 7 daily)
        await _seed_job(repo, session, backup_id="d3", tier=BackupTier.TIER_2, created_at=now - timedelta(days=3))
        # 2 backups 14 days ago (outside 7 daily, inside 4 weekly) -> keep newest of that ISO week
        await _seed_job(repo, session, backup_id="w2-old", tier=BackupTier.TIER_2, created_at=now - timedelta(days=15))
        await _seed_job(repo, session, backup_id="w2-new", tier=BackupTier.TIER_2, created_at=now - timedelta(days=14))
        # 1 backup 40 days ago (outside both 7d and 4w) -> pruned
        await _seed_job(repo, session, backup_id="too-old", tier=BackupTier.TIER_2, created_at=now - timedelta(days=40))
        # 1 pinned 60 days ago -> exempt
        await _seed_job(repo, session, backup_id="t2-pinned", tier=BackupTier.TIER_2, created_at=now - timedelta(days=60), pinned=True)
        await session.commit()

        pruned = await repo.prune_old_backups(
            ServerId("srv-1"), tier=BackupTier.TIER_2, tier2_daily=7, tier2_weekly=4, now=now
        )
        await session.commit()

        assert set(pruned) == {"d0-old", "w2-old", "too-old"}
        remaining = {j.backup_id.value for j in await repo.list_jobs(ServerId("srv-1"), tier=BackupTier.TIER_2)}
        assert remaining == {"d0-new", "d3", "w2-new", "t2-pinned"}
