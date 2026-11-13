"""Tests for backup pre-flight baseline adoption hook.

P2-1 Core Substrate — B4e
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import CasError, CasUnsupportedPlatformError, ValidationError
from app.modules.shared.value_objects import BackupJobId
from app.modules.versioning.application.baseline_adoption import BaselineAdoptionResult
from app.services.backup_orchestrator import BackupSaga
from app.tasks.definitions.backup_task import run_backup_task


@dataclass
class RecordedJob:
    backup_id: str
    status: str = "pending"
    error_message: str = ""

    def mark_failed(self, reason: str) -> None:
        self.status = "failed"
        self.error_message = reason

    def mark_failed_timeout(self, reason: str) -> None:
        self.status = "failed_timeout"
        self.error_message = reason


class FakeBackupRepository:
    def __init__(self, job: RecordedJob) -> None:
        self.job = job
        self.saved_jobs: list[RecordedJob] = []

    async def get_job(self, _backup_id: BackupJobId) -> RecordedJob:
        return self.job

    async def save_job(self, job: RecordedJob) -> None:
        self.saved_jobs.append(job)


class FakeUOW:
    def __init__(self, repo: FakeBackupRepository) -> None:
        self.session = MagicMock()
        self.repo = repo
        self.committed = False

    async def __aenter__(self) -> FakeUOW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True


class TestBackupBaselineHook:
    @pytest.mark.asyncio
    async def test_order_and_count_adoption_before_saga_execute(self) -> None:
        events: list[tuple[str]] = []

        async def fake_adopt(_server_id: str) -> BaselineAdoptionResult:
            events.append(("adopt",))
            return BaselineAdoptionResult(status="created", files_count=2, cas_ingested=2)

        async def fake_execute(*_args: Any, **_kwargs: Any) -> None:
            events.append(("execute",))

        with (
            patch(
                "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                side_effect=fake_adopt,
            ),
            patch.object(BackupSaga, "execute", side_effect=fake_execute),
            patch("app.tasks.definitions.backup_task.build_storage_backend"),
            patch("app.tasks.definitions.backup_task.build_backup_encryption"),
        ):
            res = await run_backup_task({"backup_id": "b-1", "server_id": "srv-1"})

        assert events == [("adopt",), ("execute",)]
        assert res == {"backup_id": "b-1", "server_id": "srv-1"}

    @pytest.mark.asyncio
    async def test_success_unchanged_returns_normal_dict(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        adopt_mock = AsyncMock(
            return_value=BaselineAdoptionResult(
                status="created",
                reason="",
                files_count=3,
                cas_ingested=3,
            )
        )
        saga_mock = AsyncMock()

        with (
            caplog.at_level(logging.INFO),
            patch(
                "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                adopt_mock,
            ),
            patch.object(BackupSaga, "execute", saga_mock),
            patch("app.tasks.definitions.backup_task.build_storage_backend"),
            patch("app.tasks.definitions.backup_task.build_backup_encryption"),
        ):
            res = await run_backup_task({"backup_id": "b-2", "server_id": "srv-2"})

        assert res == {"backup_id": "b-2", "server_id": "srv-2"}
        adopt_mock.assert_awaited_once_with("srv-2")
        saga_mock.assert_awaited_once()
        assert any(
            "status=created" in r.message
            and "files_count=3" in r.message
            and "cas_ingested=3" in r.message
            for r in caplog.records
            if r.levelno == logging.INFO
        )

    @pytest.mark.asyncio
    async def test_adoption_failure_when_cancelled_marks_failed_timeout(self) -> None:
        job = RecordedJob(backup_id="b-cancel")
        fake_repo = FakeBackupRepository(job)
        fake_uow = FakeUOW(fake_repo)

        adopt_mock = AsyncMock(side_effect=ValidationError("Adoption aborted"))
        saga_mock = AsyncMock()
        clear_mock = MagicMock()

        with (
            patch(
                "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                adopt_mock,
            ),
            patch.object(BackupSaga, "execute", saga_mock),
            patch("app.tasks.definitions.backup_task.build_storage_backend"),
            patch("app.tasks.definitions.backup_task.build_backup_encryption"),
            patch("app.tasks.definitions.backup_task.UnitOfWork", return_value=fake_uow),
            patch(
                "app.tasks.definitions.backup_task.SQLBackupRepository",
                return_value=fake_repo,
            ),
            patch(
                "app.tasks.definitions.backup_task.is_backup_cancelled",
                return_value=True,
            ),
            patch(
                "app.tasks.definitions.backup_task.clear_cancelled_backup",
                clear_mock,
            ),
            pytest.raises(ValidationError, match="Adoption aborted"),
        ):
            await run_backup_task({"backup_id": "b-cancel", "server_id": "srv-cancel"})

        saga_mock.assert_not_called()
        assert job.status == "failed_timeout"
        assert fake_uow.committed is True
        assert fake_repo.saved_jobs == [job]
        clear_mock.assert_called_once_with("b-cancel")

    @pytest.mark.asyncio
    async def test_adoption_failure_fails_closed(self) -> None:
        job = RecordedJob(backup_id="b-3")
        fake_repo = FakeBackupRepository(job)
        fake_uow = FakeUOW(fake_repo)

        adopt_mock = AsyncMock(side_effect=ValidationError("Tree scan truncated"))
        saga_mock = AsyncMock()

        with (
            patch(
                "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                adopt_mock,
            ),
            patch.object(BackupSaga, "execute", saga_mock),
            patch("app.tasks.definitions.backup_task.build_storage_backend"),
            patch("app.tasks.definitions.backup_task.build_backup_encryption"),
            patch("app.tasks.definitions.backup_task.UnitOfWork", return_value=fake_uow),
            patch(
                "app.tasks.definitions.backup_task.SQLBackupRepository",
                return_value=fake_repo,
            ),
            pytest.raises(ValidationError, match="Tree scan truncated"),
        ):
            await run_backup_task({"backup_id": "b-3", "server_id": "srv-3"})

        saga_mock.assert_not_called()
        assert job.status == "failed"
        assert fake_uow.committed is True
        assert fake_repo.saved_jobs == [job]

    @pytest.mark.asyncio
    async def test_unsupported_platform_continues(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        adopt_mock = AsyncMock(
            side_effect=CasUnsupportedPlatformError(
                "Artifact CAS is only supported on POSIX in this slice"
            )
        )
        saga_mock = AsyncMock()

        with (
            caplog.at_level(logging.WARNING),
            patch(
                "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                adopt_mock,
            ),
            patch.object(BackupSaga, "execute", saga_mock),
            patch("app.tasks.definitions.backup_task.build_storage_backend"),
            patch("app.tasks.definitions.backup_task.build_backup_encryption"),
        ):
            res = await run_backup_task({"backup_id": "b-4", "server_id": "srv-4"})

        assert res == {"backup_id": "b-4", "server_id": "srv-4"}
        saga_mock.assert_awaited_once()
        assert any(
            "adoption_skipped_unsupported_platform" in record.message
            and "b-4" in record.message
            and "srv-4" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        )

    @pytest.mark.asyncio
    async def test_other_cas_errors_fail_closed(self) -> None:
        job = RecordedJob(backup_id="b-5")
        fake_repo = FakeBackupRepository(job)
        fake_uow = FakeUOW(fake_repo)

        adopt_mock = AsyncMock(side_effect=CasError("CAS corrupt blob"))
        saga_mock = AsyncMock()

        with (
            patch(
                "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                adopt_mock,
            ),
            patch.object(BackupSaga, "execute", saga_mock),
            patch("app.tasks.definitions.backup_task.build_storage_backend"),
            patch("app.tasks.definitions.backup_task.build_backup_encryption"),
            patch("app.tasks.definitions.backup_task.UnitOfWork", return_value=fake_uow),
            patch(
                "app.tasks.definitions.backup_task.SQLBackupRepository",
                return_value=fake_repo,
            ),
            pytest.raises(CasError, match="CAS corrupt blob"),
        ):
            await run_backup_task({"backup_id": "b-5", "server_id": "srv-5"})

        saga_mock.assert_not_called()
        assert job.status == "failed"
        assert fake_uow.committed is True

    @pytest.mark.asyncio
    async def test_os_error_fails_closed(self) -> None:
        job = RecordedJob(backup_id="b-5b")
        fake_repo = FakeBackupRepository(job)
        fake_uow = FakeUOW(fake_repo)

        adopt_mock = AsyncMock(side_effect=OSError("Disk failure"))
        saga_mock = AsyncMock()

        with (
            patch(
                "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                adopt_mock,
            ),
            patch.object(BackupSaga, "execute", saga_mock),
            patch("app.tasks.definitions.backup_task.build_storage_backend"),
            patch("app.tasks.definitions.backup_task.build_backup_encryption"),
            patch("app.tasks.definitions.backup_task.UnitOfWork", return_value=fake_uow),
            patch(
                "app.tasks.definitions.backup_task.SQLBackupRepository",
                return_value=fake_repo,
            ),
            pytest.raises(OSError, match="Disk failure"),
        ):
            await run_backup_task({"backup_id": "b-5b", "server_id": "srv-5b"})

        saga_mock.assert_not_called()
        assert job.status == "failed"
        assert fake_uow.committed is True

    @pytest.mark.asyncio
    async def test_simple_vs_advanced_is_adoptions_job(self) -> None:
        adopt_mock = AsyncMock(
            return_value=BaselineAdoptionResult(
                status="skipped",
                reason="not_simple",
                files_count=0,
                cas_ingested=0,
            )
        )
        saga_mock = AsyncMock()

        with (
            patch(
                "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                adopt_mock,
            ),
            patch.object(BackupSaga, "execute", saga_mock),
            patch("app.tasks.definitions.backup_task.build_storage_backend"),
            patch("app.tasks.definitions.backup_task.build_backup_encryption"),
        ):
            res = await run_backup_task({"backup_id": "b-6", "server_id": "srv-adv"})

        assert res == {"backup_id": "b-6", "server_id": "srv-adv"}
        adopt_mock.assert_awaited_once_with("srv-adv")
        saga_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_quarantined_paths_logged_at_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        adopt_mock = AsyncMock(
            return_value=BaselineAdoptionResult(
                status="created",
                files_count=1,
                cas_ingested=1,
                quarantined=("config/evil.jar", "mods/suspicious.jar"),
            )
        )
        saga_mock = AsyncMock()

        with (
            caplog.at_level(logging.WARNING),
            patch(
                "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                adopt_mock,
            ),
            patch.object(BackupSaga, "execute", saga_mock),
            patch("app.tasks.definitions.backup_task.build_storage_backend"),
            patch("app.tasks.definitions.backup_task.build_backup_encryption"),
        ):
            await run_backup_task({"backup_id": "b-7", "server_id": "srv-7"})

        warning_messages = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("config/evil.jar" in msg for msg in warning_messages)
        assert any("mods/suspicious.jar" in msg for msg in warning_messages)
