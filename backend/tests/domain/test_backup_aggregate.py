from __future__ import annotations

import pytest

from app.modules.backup.domain.aggregate import BackupJob, BackupPolicy, BackupStatus, BackupType
from app.modules.backup.domain.events import (
    BackupCompletedEvent,
    BackupFailedEvent,
    BackupStartedEvent,
)
from app.modules.shared.value_objects import BackupJobId, CronExpression, ServerId


class TestBackupJob:
    def test_create_job(self) -> None:
        job = BackupJob.create(
            backup_id=BackupJobId("b1"),
            server_id=ServerId("s1"),
            backup_type=BackupType.WORLD,
        )
        assert job.status == BackupStatus.PENDING
        assert job.backup_type == BackupType.WORLD
        assert job.size_bytes == 0
        events = job.collect_events()
        assert len(events) == 1
        assert isinstance(events[0], BackupStartedEvent)

    def test_mark_completed(self) -> None:
        job = BackupJob.create(
            backup_id=BackupJobId("b1"),
            server_id=ServerId("s1"),
        )
        job.collect_events()
        job.mark_completed(size_bytes=1024, checksum="abc123")
        assert job.status == BackupStatus.COMPLETED
        assert job.size_bytes == 1024
        assert job.checksum == "abc123"
        assert job.completed_at is not None
        events = job.collect_events()
        assert len(events) == 1
        assert isinstance(events[0], BackupCompletedEvent)

    def test_mark_failed(self) -> None:
        job = BackupJob.create(
            backup_id=BackupJobId("b1"),
            server_id=ServerId("s1"),
        )
        job.collect_events()
        job.mark_failed(reason="disk full")
        assert job.status == BackupStatus.FAILED
        assert job.error_message == "disk full"
        events = job.collect_events()
        assert len(events) == 1
        assert isinstance(events[0], BackupFailedEvent)

    def test_mark_restored(self) -> None:
        job = BackupJob.create(
            backup_id=BackupJobId("b1"),
            server_id=ServerId("s1"),
        )
        job.collect_events()
        job.mark_completed(size_bytes=100, checksum="x")
        job.mark_restored()
        from app.modules.backup.domain.events import BackupRestoredEvent

        events = job.collect_events()
        assert any(isinstance(e, BackupRestoredEvent) for e in events)

    def test_default_type(self) -> None:
        job = BackupJob.create(
            backup_id=BackupJobId("b1"),
            server_id=ServerId("s1"),
        )
        assert job.backup_type == BackupType.FULL


class TestBackupPolicy:
    def test_create_policy(self) -> None:
        policy = BackupPolicy(
            server_id=ServerId("s1"),
            schedule=CronExpression("0 */6 * * *"),
        )
        assert policy.retention_days == 30
        assert policy.backup_type == BackupType.FULL
        assert policy.encryption_enabled is True
        assert policy.enabled is True

    def test_custom_policy(self) -> None:
        policy = BackupPolicy(
            server_id=ServerId("s1"),
            schedule=CronExpression("0 2 * * *"),
            retention_days=7,
            backup_type=BackupType.WORLD,
            encryption_enabled=False,
            max_backups=10,
            enabled=False,
        )
        assert policy.retention_days == 7
        assert policy.max_backups == 10
        assert policy.enabled is False
