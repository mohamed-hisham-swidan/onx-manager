"""P2-5d0 backup pinning and interim Class-C snapshot tests."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import update

import app.modules.versioning.infrastructure.class_c_snapshot as class_c_snapshot_module
from app.core import allowlist as allowlist_module
from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.exceptions import (
    BackupPinnedError,
    CasUnsupportedPlatformError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.core.persistence.db import database
from app.modules.backup.application.commands.create_backup import (
    CreateBackupCommand,
    CreateBackupHandler,
)
from app.modules.backup.application.commands.delete_backup import (
    DeleteBackupCommand,
    DeleteBackupHandler,
)
from app.modules.backup.domain.aggregate import BackupJob
from app.modules.backup.infrastructure.models import BackupJobModel
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.modules.versioning.infrastructure.class_c_snapshot import (
    COMPLETE_MARKER_NAME,
    FORMAT_VERSION,
    MANIFEST_FILENAME,
    ClassCSnapshotService,
)


async def _save_job(
    repo: SQLBackupRepository,
    backup_id: str,
    server_id: str,
    *,
    pinned: bool = False,
) -> None:
    job = BackupJob.create(
        backup_id=BackupJobId(backup_id),
        server_id=ServerId(server_id),
        pinned=pinned,
    )
    job.mark_completed(
        size_bytes=1,
        checksum="0" * 64,
        storage_path=f"{backup_id}.tar.gz.enc",
    )
    job.collect_events()
    await repo.save_job(job)


@pytest.mark.usefixtures("init_test_db")
class TestBackupPinning:
    def test_aggregate_pin_unpin(self) -> None:
        job = BackupJob.create(
            backup_id=BackupJobId("agg-pin"),
            server_id=ServerId("srv-agg"),
        )
        assert job.pinned is False
        job.pin()
        assert job.pinned is True
        job.unpin()
        assert job.pinned is False

    @pytest.mark.asyncio
    async def test_set_pinned_round_trips(self) -> None:
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            await _save_job(repo, "pin-roundtrip", "srv-pin")
            await session.commit()

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            updated = await repo.set_pinned(BackupJobId("pin-roundtrip"), True)
            assert updated.pinned is True
            await session.commit()

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            loaded = await repo.get_job(BackupJobId("pin-roundtrip"))
            assert loaded.pinned is True
            updated = await repo.set_pinned(BackupJobId("pin-roundtrip"), False)
            assert updated.pinned is False
            await session.commit()

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            loaded = await repo.get_job(BackupJobId("pin-roundtrip"))
            assert loaded.pinned is False

    @pytest.mark.asyncio
    async def test_create_command_persists_pinned(self, event_bus: EventBus) -> None:
        queue = MagicMock()
        queue.enqueue = AsyncMock()
        with patch(
            "app.modules.backup.application.commands.create_backup.get_task_queue",
            return_value=queue,
        ):
            result = await CreateBackupHandler(event_bus).handle(
                CreateBackupCommand(server_id="srv-pin-cmd", pinned=True)
            )

        assert result.success is True
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            job = await repo.get_job(BackupJobId(result.data["backup_id"]))
            assert job.pinned is True

    @pytest.mark.asyncio
    async def test_delete_handler_refuses_pinned_before_storage(
        self, event_bus: EventBus
    ) -> None:
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            await _save_job(repo, "pin-delete", "srv-pin-delete", pinned=True)
            await session.commit()

        with (
            patch(
                "app.modules.backup.application.commands.delete_backup.build_storage_backend"
            ) as storage,
            pytest.raises(BackupPinnedError) as exc,
        ):
            await DeleteBackupHandler(event_bus).handle(
                DeleteBackupCommand(backup_id="pin-delete")
            )

        assert exc.value.http_status == 409
        assert exc.value.code == "BACKUP_PINNED"
        assert exc.value.details["backup_id"] == "pin-delete"
        storage.assert_not_called()

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            still_there = await repo.get_job(BackupJobId("pin-delete"))
            assert still_there.pinned is True

    @pytest.mark.asyncio
    async def test_repository_delete_refuses_pinned(self) -> None:
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            await _save_job(repo, "pin-repo-delete", "srv-repo-delete", pinned=True)
            await session.commit()

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            with pytest.raises(BackupPinnedError):
                await repo.delete_job(BackupJobId("pin-repo-delete"))
            await session.rollback()

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            still_there = await repo.get_job(BackupJobId("pin-repo-delete"))
            assert still_there.pinned is True

    @pytest.mark.asyncio
    async def test_prune_skips_pinned_and_allows_after_unpin(self) -> None:
        server = ServerId("srv-prune")
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            for index in range(5):
                await _save_job(
                    repo,
                    f"prune-{index}",
                    "srv-prune",
                    pinned=index == 0,
                )
            await session.commit()
            base = datetime.now(UTC)
            for index in range(5):
                await session.execute(
                    update(BackupJobModel)
                    .where(BackupJobModel.id == f"prune-{index}")
                    .values(created_at=base - timedelta(days=10 - index))
                )
            await session.commit()

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            deleted = await repo.prune_old_backups(server, max_backups=3)
            await session.commit()
            assert deleted == ["prune-1"]
            pinned = await repo.get_job(BackupJobId("prune-0"))
            assert pinned.pinned is True
            remaining = {str(job.backup_id) for job in await repo.list_jobs(server)}
            assert remaining == {"prune-0", "prune-2", "prune-3", "prune-4"}

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            await repo.set_pinned(BackupJobId("prune-0"), False)
            await session.commit()
            deleted = await repo.prune_old_backups(server, max_backups=2)
            await session.commit()
            assert deleted == ["prune-0", "prune-2"]
            remaining = {str(job.backup_id) for job in await repo.list_jobs(server)}
            assert remaining == {"prune-3", "prune-4"}

    @pytest.mark.asyncio
    async def test_prune_retention_days_skips_pinned(self) -> None:
        server = ServerId("srv-retention")
        now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            await _save_job(repo, "old-pinned", "srv-retention", pinned=True)
            await _save_job(repo, "old-unpinned", "srv-retention")
            await _save_job(repo, "fresh", "srv-retention")
            await session.commit()
            for backup_id in ("old-pinned", "old-unpinned"):
                await session.execute(
                    update(BackupJobModel)
                    .where(BackupJobModel.id == backup_id)
                    .values(created_at=now - timedelta(days=30))
                )
            await session.execute(
                update(BackupJobModel)
                .where(BackupJobModel.id == "fresh")
                .values(created_at=now - timedelta(days=1))
            )
            await session.commit()

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            deleted = await repo.prune_old_backups(
                server, retention_days=7, now=now
            )
            await session.commit()
            assert deleted == ["old-unpinned"]
            remaining = {str(job.backup_id) for job in await repo.list_jobs(server)}
            assert remaining == {"old-pinned", "fresh"}


@pytest.fixture
def snapshot_env(tmp_path: Path) -> tuple[ClassCSnapshotService, HostStateLayout]:
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    layout = ensure_host_state_layout(settings)
    return ClassCSnapshotService(layout), layout


def _make_live_tree(live: Path) -> None:
    (live / "plugins" / "Essentials" / "warps").mkdir(parents=True)
    (live / "ops.json").write_text('["alice"]', encoding="utf-8")
    (live / "plugins" / "Essentials" / "warps" / "home.yml").write_text(
        "home: 1\n", encoding="utf-8"
    )
    (live / "server.properties").write_text("motd=test\n", encoding="utf-8")
    (live / "mods").mkdir()
    (live / "mods" / "example.jar").write_bytes(b"jar")
    if os.name == "posix":
        (live / "ops-link.json").symlink_to(live / "ops.json")


@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only Class-C snapshot dir-fd store; Windows = Simple-only",
)
class TestClassCSnapshotService:
    def test_create_snapshot_writes_manifest_marker_and_only_class_c(
        self, tmp_path: Path, snapshot_env: tuple[ClassCSnapshotService, HostStateLayout]
    ) -> None:
        service, layout = snapshot_env
        live = tmp_path / "live"
        _make_live_tree(live)

        result = service.create_snapshot("srv-c", live, snapshot_id="snap-1")

        root = layout.class_c_vault_dir("srv-c") / "snap-1"
        assert result.root == root
        assert result.snapshot_id == "snap-1"
        assert result.file_count == 2
        assert result.pinned is True
        assert root.is_dir()
        if os.name == "posix":
            assert stat.S_IMODE(root.stat().st_mode) == 0o700
            assert stat.S_IMODE((root / MANIFEST_FILENAME).stat().st_mode) == 0o600
            assert stat.S_IMODE((root / COMPLETE_MARKER_NAME).stat().st_mode) == 0o600

        manifest = json.loads((root / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        assert manifest["format_version"] == FORMAT_VERSION
        assert manifest["snapshot_id"] == "snap-1"
        assert manifest["server_id"] == "srv-c"
        assert manifest["pinned"] is True
        assert [entry["relpath"] for entry in manifest["files"]] == [
            "ops.json",
            "plugins/Essentials/warps/home.yml",
        ]
        assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])

        marker = json.loads(
            (root / COMPLETE_MARKER_NAME).read_text(encoding="utf-8")
        )
        assert marker["format_version"] == FORMAT_VERSION
        assert marker["snapshot_id"] == "snap-1"
        assert marker["server_id"] == "srv-c"
        assert marker["file_count"] == 2
        assert marker["completed_at"].endswith("Z")

        assert (root / "ops.json").read_text(encoding="utf-8") == '["alice"]'
        assert not (root / "server.properties").exists()
        assert not (root / "mods" / "example.jar").exists()

    def test_restore_snapshot_verifies_and_restores_files(
        self, tmp_path: Path, snapshot_env: tuple[ClassCSnapshotService, HostStateLayout]
    ) -> None:
        service, layout = snapshot_env
        live = tmp_path / "live"
        _make_live_tree(live)
        service.create_snapshot("srv-c", live, snapshot_id="snap-restore")
        manifest = json.loads(
            (layout.class_c_vault_dir("srv-c") / "snap-restore" / MANIFEST_FILENAME)
            .read_text(encoding="utf-8")
        )

        (live / "ops.json").write_text("[]", encoding="utf-8")
        (live / "plugins" / "Essentials" / "warps" / "home.yml").unlink()

        restored = service.restore_snapshot("srv-c", "snap-restore", live)

        assert restored == 2
        assert (live / "ops.json").read_text(encoding="utf-8") == '["alice"]'
        assert (
            live / "plugins" / "Essentials" / "warps" / "home.yml"
        ).read_text(encoding="utf-8") == "home: 1\n"
        if os.name == "posix":
            expected_mode = next(
                entry["mode"]
                for entry in manifest["files"]
                if entry["relpath"] == "ops.json"
            )
            assert stat.S_IMODE((live / "ops.json").stat().st_mode) == expected_mode

    def test_restore_rejects_tampered_digest(
        self, tmp_path: Path, snapshot_env: tuple[ClassCSnapshotService, HostStateLayout]
    ) -> None:
        service, layout = snapshot_env
        live = tmp_path / "live"
        _make_live_tree(live)
        service.create_snapshot("srv-c", live, snapshot_id="snap-tamper")
        snapshot_file = layout.class_c_vault_dir("srv-c") / "snap-tamper" / "ops.json"
        snapshot_file.write_text("tampered", encoding="utf-8")

        (live / "ops.json").write_text("live", encoding="utf-8")
        with pytest.raises(ValidationError, match="digest"):
            service.restore_snapshot("srv-c", "snap-tamper", live)
        assert (live / "ops.json").read_text(encoding="utf-8") == "live"

    def test_restore_rejects_missing_completion_marker(
        self, tmp_path: Path, snapshot_env: tuple[ClassCSnapshotService, HostStateLayout]
    ) -> None:
        service, layout = snapshot_env
        live = tmp_path / "live"
        _make_live_tree(live)
        service.create_snapshot("srv-c", live, snapshot_id="snap-marker")
        (
            layout.class_c_vault_dir("srv-c") / "snap-marker" / COMPLETE_MARKER_NAME
        ).unlink()

        with pytest.raises(ValidationError, match="missing"):
            service.restore_snapshot("srv-c", "snap-marker", live)

    def test_delete_refuses_pinned_then_deletes_after_unpin(
        self, tmp_path: Path, snapshot_env: tuple[ClassCSnapshotService, HostStateLayout]
    ) -> None:
        service, layout = snapshot_env
        live = tmp_path / "live"
        _make_live_tree(live)
        service.create_snapshot("srv-c", live, snapshot_id="snap-pinned", pinned=True)
        root = layout.class_c_vault_dir("srv-c") / "snap-pinned"

        with pytest.raises(BackupPinnedError) as exc:
            service.delete_snapshot("srv-c", "snap-pinned")
        assert exc.value.http_status == 409
        assert exc.value.code == "BACKUP_PINNED"
        assert root.is_dir()

        service.unpin_snapshot("srv-c", "snap-pinned")
        manifest = json.loads((root / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        assert manifest["pinned"] is False

        service.delete_snapshot("srv-c", "snap-pinned")
        assert not root.exists()

    def test_delete_unpinned_snapshot_created_unpinned(
        self, tmp_path: Path, snapshot_env: tuple[ClassCSnapshotService, HostStateLayout]
    ) -> None:
        service, layout = snapshot_env
        live = tmp_path / "live"
        _make_live_tree(live)
        service.create_snapshot("srv-c", live, snapshot_id="snap-free", pinned=False)
        root = layout.class_c_vault_dir("srv-c") / "snap-free"

        service.delete_snapshot("srv-c", "snap-free")

        assert not root.exists()


class TestClassCSnapshotNonPosixGuard:
    """Windows is Simple-only: every Class-C entrypoint must fail closed."""

    @pytest.mark.parametrize("operation", ["create", "restore", "unpin", "delete"])
    def test_non_posix_fails_closed_before_allowlist(
        self,
        operation: str,
        tmp_path: Path,
        snapshot_env: tuple[ClassCSnapshotService, HostStateLayout],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        service, layout = snapshot_env
        live = tmp_path / "live"
        _make_live_tree(live)

        def _forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError(
                f"{operation} reached the POSIX-only allowlist on a non-POSIX host"
            )

        monkeypatch.setattr(class_c_snapshot_module, "open_safe_path_fd", _forbidden)
        monkeypatch.setattr(allowlist_module, "_open_root_dir", _forbidden)
        monkeypatch.setattr(os, "name", "nt")

        calls = {
            "create": lambda: service.create_snapshot(
                "srv-c", live, snapshot_id="snap-nt"
            ),
            "restore": lambda: service.restore_snapshot("srv-c", "snap-nt", live),
            "unpin": lambda: service.unpin_snapshot("srv-c", "snap-nt"),
            "delete": lambda: service.delete_snapshot("srv-c", "snap-nt"),
        }

        with pytest.raises(CasUnsupportedPlatformError, match="POSIX host") as exc:
            calls[operation]()

        assert exc.value.code == "CAS_UNSUPPORTED_PLATFORM"
        assert exc.value.http_status == 501
        assert not layout.class_c_vault_dir("srv-c").exists()
