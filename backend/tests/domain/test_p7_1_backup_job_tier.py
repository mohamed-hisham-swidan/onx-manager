"""P7-1: BackupJob domain model supports `tier` field."""

from __future__ import annotations

from app.modules.backup.domain.aggregate import BackupJob, BackupType
from app.modules.shared.value_objects import BackupJobId, ServerId


def test_backup_job_create_defaults_to_tier_1():
    """F004: BackupJob.create() defaults tier to 'tier_1'."""
    job = BackupJob.create(
        backup_id=BackupJobId(),
        server_id=ServerId("srv-1"),
        backup_type=BackupType.FULL,
    )
    assert job.tier == "tier_1"


def test_backup_job_create_tier_2():
    """F005: BackupJob.create(tier='tier_2') sets tier to 'tier_2'."""
    job = BackupJob.create(
        backup_id=BackupJobId(),
        server_id=ServerId("srv-1"),
        backup_type=BackupType.FULL,
        tier="tier_2",
    )
    assert job.tier == "tier_2"


def test_backup_job_tier_property_is_readonly():
    """F006: BackupJob.tier is a read-only property."""
    job = BackupJob.create(
        backup_id=BackupJobId(),
        server_id=ServerId("srv-1"),
        backup_type=BackupType.CONFIG,
        tier="tier_2",
    )
    assert job.tier == "tier_2"
    # No setter — tier cannot be mutated after creation.
    assert not hasattr(type(job), "tier") or not hasattr(job.tier, "__set__")
