from __future__ import annotations

import pytest

from app.modules.backup.domain.aggregate import BackupJob, BackupTier, BackupType
from app.modules.backup.domain.events import (
    BackupCompletedEvent,
    BackupDeletedEvent,
    BackupFailedEvent,
    BackupRestoredEvent,
    BackupStartedEvent,
)
from app.modules.shared.value_objects import BackupJobId, ServerId


def test_backup_tier_enum_and_validation() -> None:
    assert BackupTier.TIER_1.value == "tier_1"
    assert BackupTier.TIER_2.value == "tier_2"

    job = BackupJob.create_tier1(BackupJobId("b-1"), ServerId("s-1"))
    assert job.tier == BackupTier.TIER_1

    job2 = BackupJob.create_tier2(BackupJobId("b-2"), ServerId("s-1"), pinned=True)
    assert job2.tier == BackupTier.TIER_2
    assert job2.pinned is True

    with pytest.raises(ValueError, match="Unsupported backup tier"):
        BackupJob(
            backup_id=BackupJobId("b-bad"),
            server_id=ServerId("s-1"),
            backup_type=BackupType.FULL,
            tier="tier_99",
        )


def test_backup_job_events_carry_tier() -> None:
    job = BackupJob.create_tier2(BackupJobId("b-t2"), ServerId("s-1"))
    job.mark_completed(size_bytes=512, checksum="deadbeef", storage_path="/tmp/a.tar.zst.enc")
    job.mark_restored()
    job.mark_deleted()
    events = job.collect_events()
    assert isinstance(events[0], BackupStartedEvent)
    assert events[0].tier == "tier_2"
    assert isinstance(events[1], BackupCompletedEvent)
    assert events[1].tier == "tier_2"
    assert isinstance(events[2], BackupRestoredEvent)
    assert events[2].tier == "tier_2"
    assert isinstance(events[3], BackupDeletedEvent)
    assert events[3].tier == "tier_2"

    job_fail = BackupJob.create_tier1(BackupJobId("b-t1"), ServerId("s-1"))
    job_fail.mark_failed("disk full")
    fail_events = job_fail.collect_events()
    assert isinstance(fail_events[1], BackupFailedEvent)
    assert fail_events[1].tier == "tier_1"
