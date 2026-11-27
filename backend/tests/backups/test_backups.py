"""Consolidated tests for backup jobs, commands, queries, saga, tiers, crypto, and Class-C snapshots."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import io
import json
import logging
import os
import stat
import struct
import sys
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import update

import app.modules.versioning.infrastructure.class_c_snapshot as class_c_snapshot_module
from app.core import allowlist as allowlist_module
from app.core.command_bus import CommandBus
from app.core.config import AppSettings
from app.core.event_bus import DomainEvent, EventBus, EventHandler
from app.core.exceptions import (
    BackupPinnedError,
    CasError,
    CasUnsupportedPlatformError,
    InsufficientStorageError,
    NotFoundError,
    ValidationError,
)
from app.core.host_state import HostStateLayout, ensure_host_state_layout
from app.core.persistence.db import database
from app.core.saga import SagaOrchestrator
from app.modules.activity.application.subscriber import ActivityEventSubscriber
from app.modules.backup.application.commands.create_backup import (
    CreateBackupCommand,
    CreateBackupHandler,
)
from app.modules.backup.application.commands.delete_backup import (
    DeleteBackupCommand,
    DeleteBackupHandler,
)
from app.modules.backup.application.commands.restore_backup import (
    RestoreBackupCommand,
    RestoreBackupHandler,
)
from app.modules.backup.application.commands.verify_backup import (
    VerifyBackupCommand,
    VerifyBackupHandler,
)
from app.modules.backup.application.queries.get_backup import GetBackupHandler, GetBackupQuery
from app.modules.backup.application.queries.list_backups import (
    ListBackupsHandler,
    ListBackupsQuery,
)
from app.modules.backup.application.restore_service import RestoreError
from app.modules.backup.domain.aggregate import (
    BackupJob,
    BackupPolicy,
    BackupStatus,
    BackupTier,
    BackupType,
)
from app.modules.backup.domain.events import (
    BackupCompletedEvent,
    BackupDeletedEvent,
    BackupFailedEvent,
    BackupRestoredEvent,
    BackupStartedEvent,
)
from app.modules.backup.infrastructure.envelope_crypto import (
    ENVELOPE_FORMAT_VERSION,
    ENVELOPE_MAGIC,
    BackupEncryptionError,
    EnvelopeBackupCipher,
    load_or_create_master_kek,
    requires_archive_encryption,
)
from app.modules.backup.infrastructure.models import BackupJobModel
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.backup.infrastructure.tier1_snapshot import (
    SAVE_OFF_MARKER_FILENAME,
    TIER1_MARKER_FILENAME,
    Tier1SnapshotError,
    collect_tier1_gc_roots,
    create_tier1_snapshot,
    discard_incomplete_snapshots,
    recover_save_off_state,
    validate_tier1_complete_marker,
)
from app.modules.backup.infrastructure.tier2_archive import (
    collect_tier2_gc_roots,
    create_tier2_archive,
)
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    RuntimeInfo,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.models import ServerModel
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import BackupJobId, CronExpression, MinecraftVersion, ServerId
from app.modules.storage.base import StorageBackend, StorageResult
from app.modules.storage.encryption import BackupEncryption
from app.modules.storage.local import LocalStorage
from app.modules.versioning.application.baseline_adoption import BaselineAdoptionResult
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.class_c_snapshot import (
    COMPLETE_MARKER_NAME,
    FORMAT_VERSION,
    MANIFEST_FILENAME,
    ClassCSnapshotService,
)
from app.modules.versioning.infrastructure.vault_crypto import MasterKek
from app.services.backup_orchestrator import CONFIG_FILES, BackupSaga
from app.tasks.definitions.backup_task import run_backup_task
from app.tasks.queue import get_task_queue


class _FakeStorage(StorageBackend):
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def write(self, path: str, data: bytes) -> StorageResult:
        self._store[path] = data
        return StorageResult(path=path, size_bytes=len(data), checksum="")

    async def read(self, path: str) -> bytes:
        return self._store.get(path, b"")

    async def delete(self, path: str) -> bool:
        return self._store.pop(path, None) is not None

    async def exists(self, path: str) -> bool:
        return path in self._store

    async def list_files(self, prefix: str) -> list:
        del prefix
        return []

    async def info(self, path: str):
        del path
        return None

    async def copy(self, source: str, destination: str) -> StorageResult:
        data = await self.read(source)
        return await self.write(destination, data)


class _FakeS3Storage(LocalStorage):
    backend_type = "s3"


def _write_text(base: Path, rel: str, content: str = "") -> Path:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


async def _seed_job(
    backup_id: str,
    server_id: str,
    *,
    tier: BackupTier = BackupTier.TIER_2,
    pinned: bool = False,
    completed: bool = True,
    storage_path: str = "",
    size_bytes: int = 1,
    checksum: str = "0" * 64,
    created_at: datetime | None = None,
) -> None:
    async with database.session_factory() as session:
        repo = SQLBackupRepository(session)
        job = BackupJob(
            backup_id=BackupJobId(backup_id),
            server_id=ServerId(server_id),
            backup_type=BackupType.FULL,
            created_at=created_at or datetime.now(UTC),
            pinned=pinned,
            tier=tier,
        )
        if completed:
            job.mark_completed(
                size_bytes=size_bytes,
                checksum=checksum,
                storage_path=storage_path or f"{backup_id}.tar.gz.enc",
            )
        job.collect_events()
        await repo.save_job(job)
        if created_at is not None:
            await session.execute(
                update(BackupJobModel)
                .where(BackupJobModel.id == backup_id)
                .values(created_at=created_at)
            )
        await session.commit()


def _build_server(server_id: ServerId, server_dir: str, *, running: bool = False) -> Server:
    server = Server.create(
        server_id=server_id,
        name="backup-test-server",
        server_type=ServerType.VANILLA,
        minecraft_version=MinecraftVersion.parse("1.21"),
        memory=MemoryAllocation(min_mb=1024, max_mb=2048),
        java_args=JavaArguments([]),
        properties=ServerProperties(port=PortNumber(25565), gamemode="survival", difficulty="easy"),
        deployment=ServerDeployment(
            location_type=LocationType.LOCAL,
            location_uri="",
            root_path=server_dir,
            working_directory=".",
            startup_jar="server.jar",
        ),
    )
    if running:
        server._status = ServerStatus.RUNNING
        server._runtime = RuntimeInfo(
            status="running",
            provider="local",
            host="127.0.0.1",
            port=25566,
            pid=12345,
            external_id="onx-save-test-session",
        )
    else:
        server._status = ServerStatus.STOPPED
    return server


# ---------------------------------------------------------------------------
# Domain Aggregate, Tiers, and Policy
# ---------------------------------------------------------------------------


class TestBackupAggregate:
    def test_job_lifecycle_events_and_tier_carrying(self) -> None:
        job = BackupJob.create(
            backup_id=BackupJobId("b1"),
            server_id=ServerId("s1"),
            backup_type=BackupType.WORLD,
        )
        assert job.status == BackupStatus.PENDING
        assert job.backup_type == BackupType.WORLD
        assert isinstance(job.collect_events()[0], BackupStartedEvent)

        job.mark_completed(size_bytes=1024, checksum="abc123")
        assert job.status == BackupStatus.COMPLETED
        assert job.size_bytes == 1024
        assert job.checksum == "abc123"
        assert job.completed_at is not None
        assert isinstance(job.collect_events()[0], BackupCompletedEvent)

        job.mark_restored()
        assert isinstance(job.collect_events()[0], BackupRestoredEvent)

        job2 = BackupJob.create_tier2(BackupJobId("b-t2"), ServerId("s1"), pinned=True)
        assert job2.tier == BackupTier.TIER_2
        assert job2.pinned is True
        job2.mark_completed(size_bytes=512, checksum="deadbeef", storage_path="/tmp/a.tar.zst.enc")
        job2.mark_restored()
        job2.mark_deleted()
        events = job2.collect_events()
        assert [type(e) for e in events] == [
            BackupStartedEvent,
            BackupCompletedEvent,
            BackupRestoredEvent,
            BackupDeletedEvent,
        ]
        assert all(e.tier == "tier_2" for e in events)

        job_fail = BackupJob.create_tier1(BackupJobId("b-t1"), ServerId("s1"))
        job_fail.mark_failed("disk full")
        assert job_fail.status == BackupStatus.FAILED
        assert job_fail.error_message == "disk full"
        fail_events = job_fail.collect_events()
        assert isinstance(fail_events[1], BackupFailedEvent)
        assert fail_events[1].tier == "tier_1"

    def test_invalid_tier_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsupported backup tier"):
            BackupJob(
                backup_id=BackupJobId("b-bad"),
                server_id=ServerId("s-1"),
                backup_type=BackupType.FULL,
                tier="tier_99",
            )

    def test_backup_policy_defaults_and_custom_values(self) -> None:
        default_policy = BackupPolicy(
            server_id=ServerId("s1"),
            schedule=CronExpression("0 */6 * * *"),
        )
        assert default_policy.retention_days == 30
        assert default_policy.backup_type == BackupType.FULL
        assert default_policy.encryption_enabled is True
        assert default_policy.enabled is True

        custom = BackupPolicy(
            server_id=ServerId("s1"),
            schedule=CronExpression("0 2 * * *"),
            retention_days=7,
            backup_type=BackupType.WORLD,
            encryption_enabled=False,
            max_backups=10,
            enabled=False,
        )
        assert custom.retention_days == 7
        assert custom.max_backups == 10
        assert custom.enabled is False


# ---------------------------------------------------------------------------
# Backup Commands & Queries
# ---------------------------------------------------------------------------


class TestBackupCommands:
    async def test_create_backup_persists_job_and_distinct_idempotency_keys(
        self, event_bus: EventBus
    ) -> None:
        cmd1 = CreateBackupCommand(server_id="srv-1", backup_type="full")
        cmd2 = CreateBackupCommand(server_id="srv-1", backup_type="full")
        assert cmd1.idempotency_key is not cmd2.idempotency_key
        assert str(cmd1.idempotency_key) != str(cmd2.idempotency_key)

        result = await CreateBackupHandler(event_bus).handle(cmd1)
        assert result.success is True
        assert "backup_id" in result.data

        async with database.session_factory() as session:
            job = await SQLBackupRepository(session).get_job(BackupJobId(result.data["backup_id"]))
            assert str(job.server_id) == "srv-1"
            assert job.backup_type == BackupType.FULL

    async def test_create_backup_invalid_type_fails(self, event_bus: EventBus) -> None:
        bus = CommandBus()
        bus.register(CreateBackupCommand, CreateBackupHandler(event_bus))
        result = await bus.send(CreateBackupCommand(server_id="srv-1", backup_type="invalid"))
        assert result.success is False

    async def test_create_backup_enqueue_failure_marks_job_failed(
        self, event_bus: EventBus
    ) -> None:
        failing_queue = get_task_queue()
        failing_queue.enqueue = AsyncMock(side_effect=RuntimeError("queue down"))

        result = await CreateBackupHandler(event_bus).handle(
            CreateBackupCommand(server_id="srv-1", backup_type="full")
        )
        assert result.success is False
        assert result.error_code == "BACKUP_ENQUEUE_FAILED"
        assert "queue down" in (result.error or "")

        async with database.session_factory() as session:
            jobs = await SQLBackupRepository(session).list_jobs()
            assert jobs and jobs[0].status == BackupStatus.FAILED
            assert "enqueue failed" in (jobs[0].error_message or "")

    async def test_create_and_list_tier_routing(self, event_bus: EventBus) -> None:
        fake_queue = SimpleNamespace(enqueue=AsyncMock())
        with patch(
            "app.modules.backup.application.commands.create_backup.get_task_queue",
            return_value=fake_queue,
        ):
            handler = CreateBackupHandler(event_bus)
            r1 = await handler.handle(CreateBackupCommand(server_id="srv-1", tier="tier_1"))
            r2 = await handler.handle(
                CreateBackupCommand(
                    server_id="srv-1",
                    tier="tier_2",
                    archive_format="tar.gz",
                    include_cas_jars=True,
                )
            )
            assert r1.success and r2.success
            assert fake_queue.enqueue.await_count == 2
            payload2 = fake_queue.enqueue.await_args_list[1].args[1]
            assert payload2["tier"] == "tier_2"
            assert payload2["archive_format"] == "tar.gz"
            assert payload2["include_cas_jars"] is True

            with pytest.raises(ValidationError):
                await handler.handle(CreateBackupCommand(server_id="srv-1", tier="tier_3"))

        list_handler = ListBackupsHandler()
        t1_items = await list_handler.handle(ListBackupsQuery(server_id="srv-1", tier="tier_1"))
        t2_items = await list_handler.handle(ListBackupsQuery(server_id="srv-1", tier="tier_2"))
        assert len(t1_items) == 1 and t1_items[0].tier == "tier_1"
        assert len(t2_items) == 1 and t2_items[0].tier == "tier_2"

    async def test_delete_backup_deletes_artifact_and_keeps_row_on_storage_error(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        storage = LocalStorage(str(tmp_path / "backups"))
        b_ok = BackupJobId()
        path_ok = f"{b_ok}.tar.gz.enc"
        await storage.write(path_ok, b"x" * 100)
        await _seed_job(str(b_ok), "srv-1", storage_path=path_ok, size_bytes=100, checksum="ab")

        with patch(
            "app.modules.backup.application.commands.delete_backup.build_storage_backend",
            return_value=storage,
        ):
            res = await DeleteBackupHandler(event_bus).handle(
                DeleteBackupCommand(backup_id=str(b_ok))
            )
        assert res.success is True
        assert not await storage.exists(path_ok)
        async with database.session_factory() as session:
            with pytest.raises(NotFoundError):
                await SQLBackupRepository(session).get_job(b_ok)

        b_err = BackupJobId()
        path_err = f"{b_err}.tar.gz.enc"
        await _seed_job(str(b_err), "srv-1", storage_path=path_err, size_bytes=100, checksum="ab")
        mock_storage = AsyncMock()
        mock_storage.delete.side_effect = OSError("disk full")
        with patch(
            "app.modules.backup.application.commands.delete_backup.build_storage_backend",
            return_value=mock_storage,
        ):
            res_err = await DeleteBackupHandler(event_bus).handle(
                DeleteBackupCommand(backup_id=str(b_err))
            )
        assert res_err.success is False
        assert path_err in (res_err.error or "")
        assert "disk full" in (res_err.error or "")
        async with database.session_factory() as session:
            job = await SQLBackupRepository(session).get_job(b_err)
            assert job.storage_path == path_err

    async def test_delete_nonexistent_backup_fails(self, event_bus: EventBus) -> None:
        bus = CommandBus()
        bus.register(DeleteBackupCommand, DeleteBackupHandler(event_bus))
        result = await bus.send(DeleteBackupCommand(backup_id="nonexistent"))
        assert result.success is False


class TestBackupQueries:
    async def test_get_and_list_backups_enrich_server_metadata(self) -> None:
        async with database.session_factory() as session:
            session.add(
                ServerModel(
                    id="srv-live",
                    name="Survival Prime",
                    server_type="paper",
                    minecraft_version="1.21.4",
                    port=25565,
                    memory_min_mb=512,
                    memory_max_mb=1024,
                )
            )
            await session.commit()

        await _seed_job("bak-live-1", "srv-live")
        await _seed_job("bak-orphan-1", "srv-gone")

        items = await ListBackupsHandler().handle(ListBackupsQuery())
        by_id = {item.backup_id: item for item in items}
        assert by_id["bak-live-1"].server_name == "Survival Prime"
        assert by_id["bak-live-1"].server_deleted is False
        assert by_id["bak-orphan-1"].server_name is None
        assert by_id["bak-orphan-1"].server_deleted is True

        filtered = await ListBackupsHandler().handle(ListBackupsQuery(server_id="srv-live"))
        assert len(filtered) == 1
        assert filtered[0].backup_id == "bak-live-1"

        live_detail = await GetBackupHandler().handle(GetBackupQuery(backup_id="bak-live-1"))
        orphan_detail = await GetBackupHandler().handle(GetBackupQuery(backup_id="bak-orphan-1"))
        assert live_detail.server_name == "Survival Prime"
        assert live_detail.server_deleted is False
        assert orphan_detail.server_name is None
        assert orphan_detail.server_deleted is True

        with pytest.raises(NotFoundError):
            await GetBackupHandler().handle(GetBackupQuery(backup_id="nonexistent"))


class TestRestoreBackupCommand:
    @pytest.fixture(autouse=True)
    def _mock_port_listening(self):
        with patch(
            "app.modules.backup.application.commands.restore_backup._port_is_listening",
            return_value=False,
        ):
            yield

    async def _create_server(
        self,
        server_id: str,
        root_path: str,
        *,
        status: str = "created",
        with_deployment: bool = True,
    ) -> None:
        deployment = (
            ServerDeployment(
                location_type=LocationType.LOCAL,
                root_path=root_path,
                working_directory=".",
            )
            if with_deployment
            else None
        )
        async with database.session_factory() as session:
            server = Server.create(
                server_id=ServerId(server_id),
                name=f"Server {server_id}",
                server_type=ServerType.VANILLA,
                minecraft_version=MinecraftVersion.parse("1.21"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments(),
                properties=ServerProperties(port=PortNumber(25565)),
                deployment=deployment,
            )
            if status == "running":
                server.start()
                server.mark_running(pid=100, port=25565)
            elif status == "crashed":
                server.start()
                server.crash(exit_code=-1, last_log_lines=["boom"])
            elif status == "stopped":
                server.start()
                server.mark_running(pid=100, port=25565)
                server.stop(reason="test")
                server.mark_stopped()
            server.collect_events()
            await SQLServerRepository(session).save(server)
            await session.commit()

    @pytest.mark.parametrize("status", ["running", "crashed"])
    async def test_restore_defers_when_server_active_or_crashed(
        self, event_bus: EventBus, tmp_path: Path, status: str
    ) -> None:
        srv_id = f"res-srv-{status}"
        bak_id = f"res-bak-{status}"
        await self._create_server(srv_id, str(tmp_path / srv_id), status=status)
        await _seed_job(bak_id, srv_id, storage_path="bak.tar.gz.enc", size_bytes=1000)

        with patch(
            "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
            AsyncMock(return_value=["world"]),
        ) as mock_restore:
            result = await RestoreBackupHandler(event_bus).handle(
                RestoreBackupCommand(backup_id=bak_id)
            )
        assert result.success is True
        assert result.data["deferred"] is True
        mock_restore.assert_not_awaited()
        async with database.session_factory() as session:
            pending = await SQLBackupRepository(session).get_pending_restore(ServerId(srv_id))
        assert pending is not None and pending[0] == bak_id

    @pytest.mark.parametrize("status", ["stopped", "created"])
    async def test_restore_runs_immediately_when_server_inactive(
        self, event_bus: EventBus, tmp_path: Path, status: str
    ) -> None:
        srv_id = f"res-srv-{status}"
        bak_id = f"res-bak-{status}"
        await self._create_server(srv_id, str(tmp_path / srv_id), status=status)
        await _seed_job(bak_id, srv_id, storage_path="bak.tar.gz.enc", size_bytes=1000)

        with patch(
            "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
            AsyncMock(return_value=["world", "world_nether"]),
        ):
            result = await RestoreBackupHandler(event_bus).handle(
                RestoreBackupCommand(backup_id=bak_id)
            )
        assert result.success is True
        assert result.data["deferred"] is False
        assert result.data["restored_items"] == ["world", "world_nether"]
        async with database.session_factory() as session:
            assert await SQLBackupRepository(session).get_pending_restore(ServerId(srv_id)) is None

    async def test_restore_uses_fresh_deployment_config(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        server_id = "res-srv-fresh"
        await self._create_server(server_id, str(tmp_path / "initial"), status="stopped")
        await _seed_job("res-bak-fresh", server_id, storage_path="bak.tar.gz.enc", size_bytes=1000)

        updated_root = str(tmp_path / "updated-path")
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = await repo.get(ServerId(server_id))
            server.update_deployment(
                ServerDeployment(
                    location_type=LocationType.LOCAL,
                    root_path=updated_root,
                    working_directory=".",
                    primary_world="my_custom_world",
                )
            )
            await repo.save(server)
            await session.commit()

        captured: dict[str, str] = {}

        async def fake_restore(_backup_id, server_dir, base_world="world"):
            captured["server_dir"] = server_dir
            captured["base_world"] = base_world
            return ["my_custom_world"]

        with patch(
            "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
            side_effect=fake_restore,
        ):
            result = await RestoreBackupHandler(event_bus).handle(
                RestoreBackupCommand(backup_id="res-bak-fresh")
            )
        assert result.success is True
        assert captured == {"server_dir": updated_root, "base_world": "my_custom_world"}

    async def test_restore_locks_server_against_concurrent_start(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from app.modules.server.application.commands.start_server import (
            StartServerCommand,
            StartServerHandler,
        )

        server_id = "res-srv-lock"
        await self._create_server(server_id, str(tmp_path / server_id), status="stopped")
        await _seed_job("res-bak-lock", server_id, storage_path="bak.tar.gz.enc", size_bytes=1000)

        start_result_during_restore = None

        async def fake_restore(_backup_id, _server_dir, base_world="world"):
            _ = base_world
            nonlocal start_result_during_restore
            async with database.session_factory() as session:
                srv = await SQLServerRepository(session).get(ServerId(server_id))
                assert srv.status == ServerStatus.RESTORING
            start_result_during_restore = await StartServerHandler(event_bus).handle(
                StartServerCommand(server_id=server_id)
            )
            return ["world"]

        with patch(
            "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
            side_effect=fake_restore,
        ):
            result = await RestoreBackupHandler(event_bus).handle(
                RestoreBackupCommand(backup_id="res-bak-lock")
            )
        assert result.success is True
        assert start_result_during_restore is not None
        assert start_result_during_restore.success is False
        assert start_result_during_restore.error_code == "SERVER_BUSY"

        async with database.session_factory() as session:
            srv = await SQLServerRepository(session).get(ServerId(server_id))
            assert srv.status == ServerStatus.STOPPED

    async def test_restore_error_paths_rejected(self, event_bus: EventBus, tmp_path: Path) -> None:
        # 1. RestoreError surfaced cleanly
        await self._create_server("res-srv-fail", str(tmp_path / "f1"), status="stopped")
        await _seed_job(
            "res-bak-fail", "res-srv-fail", storage_path="bak.tar.gz.enc", size_bytes=1000
        )
        with patch(
            "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
            AsyncMock(side_effect=RestoreError("checksum mismatch")),
        ):
            res_fail = await RestoreBackupHandler(event_bus).handle(
                RestoreBackupCommand(backup_id="res-bak-fail")
            )
        assert res_fail.success is False
        assert res_fail.error_code == "RESTORE_FAILED"

        # 2. Empty storage_path rejected before invoking restore
        await self._create_server("res-srv-noart", str(tmp_path / "f2"), status="stopped")
        async with database.session_factory() as session:
            job = BackupJob.create(
                backup_id=BackupJobId("res-bak-noart"), server_id=ServerId("res-srv-noart")
            )
            job.mark_completed(size_bytes=1000, checksum="abc123", storage_path="")
            await SQLBackupRepository(session).save_job(job)
            await session.commit()
        with patch(
            "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
            AsyncMock(return_value=["world"]),
        ) as mock_restore:
            res_noart = await RestoreBackupHandler(event_bus).handle(
                RestoreBackupCommand(backup_id="res-bak-noart")
            )
        assert res_noart.success is False
        assert res_noart.error_code == "BACKUP_STORAGE_MISSING"
        mock_restore.assert_not_awaited()

        # 3. Missing deployment rejected
        await self._create_server(
            "res-srv-nodeploy", str(tmp_path / "f3"), status="stopped", with_deployment=False
        )
        await _seed_job("res-bak-nodeploy", "res-srv-nodeploy", storage_path="bak.tar.gz.enc")
        res_nodeploy = await RestoreBackupHandler(event_bus).handle(
            RestoreBackupCommand(backup_id="res-bak-nodeploy")
        )
        assert res_nodeploy.success is False
        assert res_nodeploy.error_code == "NO_DEPLOYMENT"

        # 4. Nonexistent backup rejected via CommandBus
        bus = CommandBus()
        bus.register(RestoreBackupCommand, RestoreBackupHandler(event_bus))
        assert (await bus.send(RestoreBackupCommand(backup_id="nonexistent"))).success is False


class TestVerifyBackupCommand:
    async def test_verify_valid_and_missing_archive_artifacts(self, event_bus: EventBus) -> None:
        artifact = b"encrypted-backup-data"
        checksum = hashlib.sha256(artifact).hexdigest()
        await _seed_job(
            "vrf-bak-1",
            "srv-1",
            storage_path="vrf-bak-1.tar.gz.enc",
            size_bytes=len(artifact),
            checksum=checksum,
        )
        fake_storage = _FakeStorage()
        await fake_storage.write("vrf-bak-1.tar.gz.enc", artifact)

        with patch(
            "app.modules.backup.application.commands.verify_backup.build_storage_backend",
            return_value=fake_storage,
        ):
            ok = await VerifyBackupHandler(event_bus).handle(
                VerifyBackupCommand(backup_id="vrf-bak-1")
            )
        assert ok.success is True
        assert ok.data["valid"] is True
        assert ok.data["checksum_valid"] is True
        assert ok.data["size_valid"] is True

        await _seed_job(
            "vrf-bak-2",
            "srv-1",
            storage_path="missing.tar.gz.enc",
            size_bytes=5000,
            checksum="sha256-abc",
        )
        with patch(
            "app.modules.backup.application.commands.verify_backup.build_storage_backend",
            return_value=_FakeStorage(),
        ):
            bad = await VerifyBackupHandler(event_bus).handle(
                VerifyBackupCommand(backup_id="vrf-bak-2")
            )
        assert bad.success is True
        assert bad.data["valid"] is False
        assert bad.data["artifact_present"] is False
        assert bad.data["artifact_error"]

    async def test_verify_tier1_snapshot_valid_and_tampered(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        server_dir = tmp_path / "srv-t1"
        (server_dir / "world").mkdir(parents=True)
        (server_dir / "world" / "level.dat").write_bytes(b"level-bytes")
        (server_dir / "server.properties").write_text("motd=T1\n", encoding="utf-8")

        snap = await create_tier1_snapshot(
            server_id="srv-t1",
            server_dir=server_dir,
            snapshots_root=tmp_path / "snapshots",
            backup_id="vrf-t1-1",
            force_no_reflink=True,
        )
        await _seed_job(
            "vrf-t1-1",
            "srv-t1",
            tier=BackupTier.TIER_1,
            storage_path=snap.snapshot_dir,
            size_bytes=snap.size_bytes,
            checksum=snap.checksum,
        )

        handler = VerifyBackupHandler(event_bus)
        ok_res = await handler.handle(VerifyBackupCommand(backup_id="vrf-t1-1"))
        assert ok_res.success is True
        assert ok_res.data["valid"] is True
        assert ok_res.data["artifact_present"] is True
        assert ok_res.data["artifact_matches"] is True
        assert ok_res.data["artifact_error"] is None

        (tmp_path / "snapshots" / "srv-t1" / "vrf-t1-1" / TIER1_MARKER_FILENAME).unlink()
        bad_res = await handler.handle(VerifyBackupCommand(backup_id="vrf-t1-1"))
        assert bad_res.success is True
        assert bad_res.data["valid"] is False
        assert bad_res.data["artifact_present"] is True
        assert bad_res.data["artifact_matches"] is False
        assert "Missing" in (bad_res.data["artifact_error"] or "") or "Incomplete" in (
            bad_res.data["artifact_error"] or ""
        )

    async def test_verify_nonexistent_backup_fails(self, event_bus: EventBus) -> None:
        bus = CommandBus()
        bus.register(VerifyBackupCommand, VerifyBackupHandler(event_bus))
        result = await bus.send(VerifyBackupCommand(backup_id="nonexistent"))
        assert result.success is False


# ---------------------------------------------------------------------------
# Backup Pinning & Tier-Aware Pruning
# ---------------------------------------------------------------------------


class TestBackupPinningAndPruning:
    def test_pinned_column_default_and_aggregate_toggle(self) -> None:
        column = BackupJobModel.__table__.c.pinned
        assert column.nullable is False
        assert column.default is not None and column.default.arg is False

        job = BackupJob.create(backup_id=BackupJobId("agg-pin"), server_id=ServerId("srv-agg"))
        assert job.pinned is False
        job.pin()
        assert job.pinned is True
        job.unpin()
        assert job.pinned is False

    async def test_pinned_persists_through_model_repo_and_create_command(
        self, event_bus: EventBus
    ) -> None:
        async with database.session_factory() as session:
            session.add(BackupJobModel(id="bak-pin-f", server_id="srv-1"))
            session.add(BackupJobModel(id="bak-pin-t", server_id="srv-1", pinned=True))
            await session.commit()
        async with database.session_factory() as session:
            assert (await session.get(BackupJobModel, "bak-pin-f")).pinned is False
            assert (await session.get(BackupJobModel, "bak-pin-t")).pinned is True

        await _seed_job("pin-rt", "srv-pin")
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            assert (await repo.set_pinned(BackupJobId("pin-rt"), True)).pinned is True
            await session.commit()
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            assert (await repo.get_job(BackupJobId("pin-rt"))).pinned is True
            assert (await repo.set_pinned(BackupJobId("pin-rt"), False)).pinned is False
            await session.commit()

        queue = MagicMock(enqueue=AsyncMock())
        with patch(
            "app.modules.backup.application.commands.create_backup.get_task_queue",
            return_value=queue,
        ):
            res = await CreateBackupHandler(event_bus).handle(
                CreateBackupCommand(server_id="srv-pin-cmd", pinned=True)
            )
        assert res.success is True
        async with database.session_factory() as session:
            assert (
                await SQLBackupRepository(session).get_job(BackupJobId(res.data["backup_id"]))
            ).pinned is True

    async def test_pinned_backup_refuses_delete_in_handler_and_repository(
        self, event_bus: EventBus
    ) -> None:
        await _seed_job("pin-del", "srv-pin-del", pinned=True)

        with (
            patch(
                "app.modules.backup.application.commands.delete_backup.build_storage_backend"
            ) as storage,
            pytest.raises(BackupPinnedError) as exc,
        ):
            await DeleteBackupHandler(event_bus).handle(DeleteBackupCommand(backup_id="pin-del"))
        assert exc.value.http_status == 409
        assert exc.value.code == "BACKUP_PINNED"
        storage.assert_not_called()

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            with pytest.raises(BackupPinnedError):
                await repo.delete_job(BackupJobId("pin-del"))
            await session.rollback()
            assert (await repo.get_job(BackupJobId("pin-del"))).pinned is True

    async def test_prune_max_backups_and_retention_days_skip_pinned(self) -> None:
        server = ServerId("srv-prune")
        base = datetime.now(UTC)
        for index in range(5):
            await _seed_job(
                f"prune-{index}",
                "srv-prune",
                pinned=index == 0,
                created_at=base - timedelta(days=10 - index),
            )

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            deleted = await repo.prune_old_backups(server, max_backups=3)
            await session.commit()
            assert deleted == ["prune-1"]
            assert {str(j.backup_id) for j in await repo.list_jobs(server)} == {
                "prune-0",
                "prune-2",
                "prune-3",
                "prune-4",
            }
            await repo.set_pinned(BackupJobId("prune-0"), False)
            await session.commit()
            deleted2 = await repo.prune_old_backups(server, max_backups=2)
            await session.commit()
            assert deleted2 == ["prune-0", "prune-2"]

        now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
        await _seed_job("ret-pin", "srv-ret", pinned=True, created_at=now - timedelta(days=30))
        await _seed_job("ret-old", "srv-ret", created_at=now - timedelta(days=30))
        await _seed_job("ret-fresh", "srv-ret", created_at=now - timedelta(days=1))
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            assert await repo.prune_old_backups(ServerId("srv-ret"), retention_days=7, now=now) == [
                "ret-old"
            ]
            await session.commit()
            assert {str(j.backup_id) for j in await repo.list_jobs(ServerId("srv-ret"))} == {
                "ret-pin",
                "ret-fresh",
            }

    async def test_tier1_fifo_5_and_tier2_7_daily_4_weekly_pruning(self) -> None:
        now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
        for i in range(6):
            await _seed_job(
                f"t1-{i}",
                "srv-tprune",
                tier=BackupTier.TIER_1,
                created_at=now - timedelta(hours=6 - i),
            )
        await _seed_job(
            "t1-pinned",
            "srv-tprune",
            tier=BackupTier.TIER_1,
            created_at=now - timedelta(days=10),
            pinned=True,
        )
        await _seed_job(
            "t2-keep",
            "srv-tprune",
            tier=BackupTier.TIER_2,
            created_at=now - timedelta(days=20),
        )

        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            pruned_t1 = await repo.prune_old_backups(
                ServerId("srv-tprune"), tier=BackupTier.TIER_1, tier1_keep=5, now=now
            )
            await session.commit()
            assert pruned_t1 == ["t1-0"]
            assert {
                j.backup_id.value
                for j in await repo.list_jobs(ServerId("srv-tprune"), tier=BackupTier.TIER_1)
            } == {"t1-1", "t1-2", "t1-3", "t1-4", "t1-5", "t1-pinned"}
            assert {
                j.backup_id.value
                for j in await repo.list_jobs(ServerId("srv-tprune"), tier=BackupTier.TIER_2)
            } == {"t2-keep"}

        # Tier-2 GFS: 7 daily union 4 weekly + pinned exempt
        await _seed_job(
            "d0-old", "srv-t2gfs", tier=BackupTier.TIER_2, created_at=now - timedelta(hours=3)
        )
        await _seed_job("d0-new", "srv-t2gfs", tier=BackupTier.TIER_2, created_at=now)
        await _seed_job(
            "d3", "srv-t2gfs", tier=BackupTier.TIER_2, created_at=now - timedelta(days=3)
        )
        await _seed_job(
            "w2-old", "srv-t2gfs", tier=BackupTier.TIER_2, created_at=now - timedelta(days=15)
        )
        await _seed_job(
            "w2-new", "srv-t2gfs", tier=BackupTier.TIER_2, created_at=now - timedelta(days=14)
        )
        await _seed_job(
            "too-old", "srv-t2gfs", tier=BackupTier.TIER_2, created_at=now - timedelta(days=40)
        )
        await _seed_job(
            "t2-pinned",
            "srv-t2gfs",
            tier=BackupTier.TIER_2,
            created_at=now - timedelta(days=60),
            pinned=True,
        )
        async with database.session_factory() as session:
            repo = SQLBackupRepository(session)
            pruned_t2 = await repo.prune_old_backups(
                ServerId("srv-t2gfs"),
                tier=BackupTier.TIER_2,
                tier2_daily=7,
                tier2_weekly=4,
                now=now,
            )
            await session.commit()
            assert set(pruned_t2) == {"d0-old", "w2-old", "too-old"}
            assert {
                j.backup_id.value
                for j in await repo.list_jobs(ServerId("srv-t2gfs"), tier=BackupTier.TIER_2)
            } == {"d0-new", "d3", "w2-new", "t2-pinned"}


# ---------------------------------------------------------------------------
# Class-C Snapshot Vault
# ---------------------------------------------------------------------------


@pytest.fixture
def snapshot_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ClassCSnapshotService, HostStateLayout]:
    monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)
    monkeypatch.setenv("ONX_MASTER_KEK", "a5" * 32)
    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    return ClassCSnapshotService(ensure_host_state_layout(settings)), ensure_host_state_layout(
        settings
    )


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


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only Class-C snapshot dir-fd store")
class TestClassCSnapshotService:
    def test_create_snapshot_encrypts_only_class_c_files(
        self, tmp_path: Path, snapshot_env: tuple[ClassCSnapshotService, HostStateLayout]
    ) -> None:
        service, layout = snapshot_env
        live = tmp_path / "live"
        _make_live_tree(live)

        result = service.create_snapshot("srv-c", live, snapshot_id="snap-1")
        root = layout.class_c_vault_dir("srv-c") / "snap-1"
        assert result.root == root
        assert result.file_count == 2
        assert result.pinned is True
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE((root / MANIFEST_FILENAME).stat().st_mode) == 0o600
        assert stat.S_IMODE((root / COMPLETE_MARKER_NAME).stat().st_mode) == 0o600
        assert stat.S_IMODE((root / "blobs").stat().st_mode) == 0o700

        manifest = json.loads((root / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        assert manifest["format_version"] == FORMAT_VERSION == 2
        assert [e["relpath"] for e in manifest["files"]] == [
            "ops.json",
            "plugins/Essentials/warps/home.yml",
        ]
        assert len(manifest["wrapped_dek"]) == 96
        assert len(manifest["dek_wrap_nonce"]) == 24
        assert not (root / "ops.json").exists()
        assert not (root / "server.properties").exists()
        assert not (root / "mods" / "example.jar").exists()

        blob = root / manifest["files"][0]["blob_relpath"]
        assert b'["alice"]' not in blob.read_bytes()
        assert stat.S_IMODE(blob.stat().st_mode) == 0o600

        marker = json.loads((root / COMPLETE_MARKER_NAME).read_text(encoding="utf-8"))
        assert marker["file_count"] == 2 and marker["completed_at"].endswith("Z")

    def test_restore_snapshot_verifies_integrity_marker_and_version(
        self, tmp_path: Path, snapshot_env: tuple[ClassCSnapshotService, HostStateLayout]
    ) -> None:
        service, layout = snapshot_env
        live = tmp_path / "live"
        _make_live_tree(live)
        service.create_snapshot("srv-c", live, snapshot_id="snap-res")
        root = layout.class_c_vault_dir("srv-c") / "snap-res"
        manifest = json.loads((root / MANIFEST_FILENAME).read_text(encoding="utf-8"))

        # Normal restore
        (live / "ops.json").write_text("[]", encoding="utf-8")
        (live / "plugins" / "Essentials" / "warps" / "home.yml").unlink()
        assert service.restore_snapshot("srv-c", "snap-res", live) == 2
        assert (live / "ops.json").read_text(encoding="utf-8") == '["alice"]'
        assert (live / "plugins" / "Essentials" / "warps" / "home.yml").read_text(
            encoding="utf-8"
        ) == "home: 1\n"
        expected_mode = next(e["mode"] for e in manifest["files"] if e["relpath"] == "ops.json")
        assert stat.S_IMODE((live / "ops.json").stat().st_mode) == expected_mode

        # Tampered blob fails digest check
        blob = root / next(
            e["blob_relpath"] for e in manifest["files"] if e["relpath"] == "ops.json"
        )
        orig_blob = blob.read_bytes()
        tampered = bytearray(orig_blob)
        tampered[-1] ^= 0x01
        blob.write_bytes(bytes(tampered))
        (live / "ops.json").write_text("live", encoding="utf-8")
        with pytest.raises(ValidationError, match="digest"):
            service.restore_snapshot("srv-c", "snap-res", live)
        assert (live / "ops.json").read_text(encoding="utf-8") == "live"
        blob.write_bytes(orig_blob)

        # Retired format version 1 rejected
        for name in (MANIFEST_FILENAME, COMPLETE_MARKER_NAME):
            p = root / name
            payload = json.loads(p.read_text(encoding="utf-8"))
            payload["format_version"] = 1
            p.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValidationError, match="format_version"):
            service.restore_snapshot("srv-c", "snap-res", live)

        # Missing completion marker rejected
        (root / COMPLETE_MARKER_NAME).unlink()
        with pytest.raises(ValidationError, match="missing"):
            service.restore_snapshot("srv-c", "snap-res", live)

    def test_delete_refuses_pinned_and_allows_unpinned(
        self, tmp_path: Path, snapshot_env: tuple[ClassCSnapshotService, HostStateLayout]
    ) -> None:
        service, layout = snapshot_env
        live = tmp_path / "live"
        _make_live_tree(live)

        service.create_snapshot("srv-c", live, snapshot_id="snap-pin", pinned=True)
        root = layout.class_c_vault_dir("srv-c") / "snap-pin"
        with pytest.raises(BackupPinnedError) as exc:
            service.delete_snapshot("srv-c", "snap-pin")
        assert exc.value.http_status == 409 and exc.value.code == "BACKUP_PINNED"
        service.unpin_snapshot("srv-c", "snap-pin")
        service.delete_snapshot("srv-c", "snap-pin")
        assert not root.exists()

        service.create_snapshot("srv-c", live, snapshot_id="snap-free", pinned=False)
        service.delete_snapshot("srv-c", "snap-free")
        assert not (layout.class_c_vault_dir("srv-c") / "snap-free").exists()


class TestClassCSnapshotNonPosixGuard:
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
            raise AssertionError(f"{operation} reached POSIX allowlist on non-POSIX host")

        monkeypatch.setattr(class_c_snapshot_module, "open_safe_path_fd", _forbidden)
        monkeypatch.setattr(allowlist_module, "_open_root_dir", _forbidden)
        monkeypatch.setattr(os, "name", "nt")

        calls = {
            "create": lambda: service.create_snapshot("srv-c", live, snapshot_id="snap-nt"),
            "restore": lambda: service.restore_snapshot("srv-c", "snap-nt", live),
            "unpin": lambda: service.unpin_snapshot("srv-c", "snap-nt"),
            "delete": lambda: service.delete_snapshot("srv-c", "snap-nt"),
        }
        with pytest.raises(CasUnsupportedPlatformError, match="POSIX host") as exc:
            calls[operation]()
        assert exc.value.code == "CAS_UNSUPPORTED_PLATFORM" and exc.value.http_status == 501
        assert not layout.class_c_vault_dir("srv-c").exists()


# ---------------------------------------------------------------------------
# Envelope Crypto, Tier-1 Snapshots, & Tier-2 Archives
# ---------------------------------------------------------------------------


class TestEnvelopeCryptoAndTiers:
    def test_envelope_multichunk_roundtrip_tamper_and_reorder_resistance(self) -> None:
        kek = MasterKek(kek_version=1, key_bytes=b"\x11" * 32)
        wrong_kek = MasterKek(kek_version=1, key_bytes=b"\x22" * 32)
        cipher = EnvelopeBackupCipher(kek, chunk_size=65536)

        plaintext = os.urandom(65536 * 2 + 12345)
        encrypted = cipher.encrypt_bytes(plaintext)
        assert encrypted.startswith(ENVELOPE_MAGIC + bytes([ENVELOPE_FORMAT_VERSION]))
        assert cipher.decrypt_bytes(encrypted) == plaintext

        with pytest.raises(BackupEncryptionError, match="unwrap"):
            EnvelopeBackupCipher(wrong_kek).decrypt_bytes(encrypted)
        with pytest.raises(BackupEncryptionError, match="(Truncated|final chunk)"):
            cipher.decrypt_bytes(encrypted[:-20])
        with pytest.raises(BackupEncryptionError, match="trailing"):
            cipher.decrypt_bytes(encrypted + b"\x00\x00\x00\x20\x01" + b"\xaa" * 32)

        mutated = bytearray(encrypted)
        mutated[-5] ^= 0xFF
        with pytest.raises(BackupEncryptionError, match="Integrity"):
            cipher.decrypt_bytes(bytes(mutated))

        # Empty & chunk reorder
        small_cipher = EnvelopeBackupCipher(
            MasterKek(kek_version=1, key_bytes=b"\x33" * 32), chunk_size=64
        )
        assert small_cipher.decrypt_bytes(small_cipher.encrypt_bytes(b"")) == b""
        enc2 = small_cipher.encrypt_bytes(b"A" * 64 + b"B" * 64)
        hdr_prefix_len = struct.calcsize(">8sBI")
        _, _, hdr_len = struct.unpack(">8sBI", enc2[:hdr_prefix_len])
        pos = hdr_prefix_len + hdr_len
        c0_len, _ = struct.unpack(">IB", enc2[pos : pos + 5])
        c0 = enc2[pos : pos + 5 + c0_len]
        pos2 = pos + 5 + c0_len
        c1_len, _ = struct.unpack(">IB", enc2[pos2 : pos2 + 5])
        c1 = enc2[pos2 : pos2 + 5 + c1_len]
        with pytest.raises(BackupEncryptionError, match="(Integrity|trailing)"):
            small_cipher.decrypt_bytes(enc2[:pos] + c1 + c0)

    def test_encryption_policy_and_kek_file_permissions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONX_MASTER_KEK", raising=False)
        monkeypatch.delenv("ONX_MASTER_KEK_FILE", raising=False)
        assert requires_archive_encryption(has_class_c=True, storage_backend="local") is True
        assert requires_archive_encryption(has_class_c=False, storage_backend="s3") is True
        assert requires_archive_encryption(has_class_c=False, storage_backend="local") is False

        kek_path = tmp_path / "keys" / "master.kek"
        kek = load_or_create_master_kek(kek_file_path=kek_path, allow_create=True)
        assert len(kek.key_bytes) == 32
        if os.name == "posix":
            assert stat.S_IMODE(kek_path.stat().st_mode) == 0o600

    async def test_tier1_quiescent_snapshot_recovery_and_space_checks(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "srv"
        snaps_root = tmp_path / "snaps"
        (server_dir / "world").mkdir(parents=True)
        (server_dir / "world" / "level.dat").write_bytes(b"level-data")
        (server_dir / "ops.json").write_text('[{"name":"alice"}]', encoding="utf-8")
        (server_dir / "server.properties").write_text("motd=Hello\n", encoding="utf-8")
        (server_dir / "onx-jars.lock.json").write_text(
            json.dumps(
                {"files": [{"path": "mods/a.jar", "sha256": "a" * 64, "origin": "modrinth"}]}
            ),
            encoding="utf-8",
        )

        rcon_cmds: list[str] = []

        async def ok_rcon(cmd: str) -> str:
            rcon_cmds.append(cmd)
            if cmd == "save-all flush":
                (server_dir / "world" / "level.dat").write_bytes(b"level-data-flushed")
            return "ok"

        res = await create_tier1_snapshot(
            server_id="srv-1",
            server_dir=server_dir,
            snapshots_root=snaps_root,
            backup_id="snap-1",
            is_running=True,
            rcon_send=ok_rcon,
            force_no_reflink=True,
        )
        assert rcon_cmds == ["save-off", "save-all flush", "save-on"]
        assert res.quiesced is True
        assert not (server_dir / ".onx-manager" / SAVE_OFF_MARKER_FILENAME).exists()
        snap_dir = Path(res.snapshot_dir)
        assert (snap_dir / "class_e" / "world" / "level.dat").read_bytes() == b"level-data-flushed"
        assert validate_tier1_complete_marker(snap_dir)["backup_id"] == "snap-1"
        assert collect_tier1_gc_roots(snaps_root / "srv-1") == {"a" * 64}

        # save-on guaranteed even when flush fails + startup recovery helper
        fail_cmds: list[str] = []

        async def fail_rcon(cmd: str) -> str:
            fail_cmds.append(cmd)
            if cmd == "save-all flush":
                raise RuntimeError("flush boom")
            return "ok"

        with pytest.raises(RuntimeError, match="flush boom"):
            await create_tier1_snapshot(
                server_id="srv-1",
                server_dir=server_dir,
                snapshots_root=snaps_root,
                backup_id="snap-fail",
                is_running=True,
                rcon_send=fail_rcon,
                force_no_reflink=True,
            )
        assert fail_cmds == ["save-off", "save-all flush", "save-on"]

        meta = server_dir / ".onx-manager"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / SAVE_OFF_MARKER_FILENAME).write_text(
            '{"rcon_save_off_active": true}', encoding="utf-8"
        )
        rec_cmds: list[str] = []

        async def rec_rcon(cmd: str) -> str:
            rec_cmds.append(cmd)
            return "ok"

        assert await recover_save_off_state(meta, rec_rcon) is True
        assert rec_cmds == ["save-on"]
        assert not (meta / SAVE_OFF_MARKER_FILENAME).exists()

        # Space check & incomplete snapshot discard
        with (
            patch(
                "app.modules.backup.infrastructure.tier1_snapshot.shutil.disk_usage",
                return_value=SimpleNamespace(free=1),
            ),
            pytest.raises(InsufficientStorageError),
        ):
            await create_tier1_snapshot(
                server_id="srv-1",
                server_dir=server_dir,
                snapshots_root=snaps_root,
                backup_id="snap-nospace",
            )
        incomplete = snaps_root / "srv-1" / "incomplete-1"
        incomplete.mkdir(parents=True, exist_ok=True)
        (incomplete / "class_e").mkdir()
        with pytest.raises(Tier1SnapshotError):
            validate_tier1_complete_marker(incomplete)
        assert discard_incomplete_snapshots(snaps_root / "srv-1") == ["incomplete-1"]
        assert not incomplete.exists()

    async def test_tier1_and_lec_store_import_without_fcntl_for_windows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_import = __import__

        def _no_fcntl(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "fcntl":
                raise ImportError("No module named 'fcntl' (simulated Windows)")
            return real_import(name, globals, locals, fromlist, level)

        for mod_name in (
            "app.modules.backup.infrastructure.tier1_snapshot",
            "app.modules.versioning.infrastructure.lec_store",
        ):
            monkeypatch.delitem(sys.modules, mod_name, raising=False)
        monkeypatch.delitem(sys.modules, "fcntl", raising=False)
        monkeypatch.setattr("builtins.__import__", _no_fcntl)

        t1_mod = importlib.import_module("app.modules.backup.infrastructure.tier1_snapshot")
        lec_mod = importlib.import_module("app.modules.versioning.infrastructure.lec_store")
        assert t1_mod.fcntl is None and lec_mod.fcntl is None

        root = tmp_path / "srv-nt"
        (root / "world").mkdir(parents=True)
        (root / "world" / "level.dat").write_bytes(b"nt-data")
        monkeypatch.setattr(t1_mod.os, "name", "nt")
        with t1_mod.open_safe_read_handle(root, "world/level.dat") as fh:
            assert fh.read() == b"nt-data"

    @pytest.mark.skipif(os.name != "posix", reason="ArtifactCas requires POSIX")
    @pytest.mark.parametrize("fmt", ["tar.zst", "tar.gz"])
    async def test_tier2_archive_formats_cas_bundling_and_encryption(
        self, tmp_path: Path, fmt: str
    ) -> None:
        server_dir = tmp_path / "srv"
        cas = ArtifactCas(tmp_path / "cas")
        storage = LocalStorage(str(tmp_path / "backups"))
        kek = MasterKek(kek_version=1, key_bytes=b"\x44" * 32)
        (server_dir / "world").mkdir(parents=True)
        (server_dir / "world" / "level.dat").write_bytes(b"world-bytes")
        (server_dir / "server.properties").write_text("motd=Tier2\n", encoding="utf-8")
        (server_dir / "ops.json").write_text('[{"name":"admin"}]', encoding="utf-8")
        user_sha = cas.put_bytes(b"custom-user-mod-jar")
        modrinth_sha = cas.put_bytes(b"public-modrinth-jar")
        (server_dir / "onx-jars.lock.json").write_text(
            json.dumps(
                {
                    "files": [
                        {"path": "mods/user.jar", "sha256": user_sha, "origin": "user"},
                        {"path": "mods/public.jar", "sha256": modrinth_sha, "origin": "modrinth"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        res_light = await create_tier2_archive(
            server_id="srv-1",
            server_dir=server_dir,
            backup_id=f"b-light-{fmt}",
            storage=storage,
            archive_format=fmt,  # type: ignore[arg-type]
            include_cas_jars=False,
            kek=kek,
            cas=cas,
        )
        assert res_light.encrypted is True
        assert res_light.bundled_cas_digests == ()
        assert set(res_light.lockfile_cas_digests) == {user_sha, modrinth_sha}

        res_user = await create_tier2_archive(
            server_id="srv-1",
            server_dir=server_dir,
            backup_id=f"b-user-{fmt}",
            storage=storage,
            archive_format=fmt,  # type: ignore[arg-type]
            include_cas_jars=True,
            kek=kek,
            cas=cas,
        )
        assert res_user.bundled_cas_digests == (user_sha,)
        enc_bytes = await storage.read(res_user.storage_path)
        assert hashlib.sha256(enc_bytes).hexdigest() == res_user.checksum
        assert len(EnvelopeBackupCipher(kek).decrypt_bytes(enc_bytes)) > 0
        assert collect_tier2_gc_roots([server_dir]) == {user_sha, modrinth_sha}

    @pytest.mark.skipif(os.name != "posix", reason="ArtifactCas requires POSIX")
    async def test_tier2_mandatory_encryption_rejects_opt_out(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "srv"
        cas = ArtifactCas(tmp_path / "cas")
        local_store = LocalStorage(str(tmp_path / "local"))
        s3_store = _FakeS3Storage(str(tmp_path / "s3"))
        (server_dir / "world").mkdir(parents=True)
        (server_dir / "world" / "level.dat").write_bytes(b"world-bytes")
        (server_dir / "server.properties").write_text("motd=Tier2\n", encoding="utf-8")
        (server_dir / "ops.json").write_text('[{"name":"admin"}]', encoding="utf-8")
        cas_sha = cas.put_bytes(b"jar")
        (server_dir / "onx-jars.lock.json").write_text(
            json.dumps({"files": [{"path": "mods/u.jar", "sha256": cas_sha, "origin": "user"}]}),
            encoding="utf-8",
        )

        with pytest.raises(ValidationError, match="mandatory"):
            await create_tier2_archive(
                server_id="srv-1",
                server_dir=server_dir,
                backup_id="b-noenc-c",
                storage=local_store,
                archive_format="tar.gz",
                encrypt=False,
            )

        (server_dir / "ops.json").unlink()
        res_plain = await create_tier2_archive(
            server_id="srv-1",
            server_dir=server_dir,
            backup_id="b-plain-local",
            storage=local_store,
            archive_format="tar.gz",
            encrypt=False,
        )
        assert res_plain.encrypted is False
        with tarfile.open(tmp_path / "local" / res_plain.storage_path, "r:gz") as tf:
            manifest = json.loads(tf.extractfile("manifest.json").read().decode("utf-8"))  # type: ignore[union-attr]
            assert manifest["tier"] == "tier_2" and manifest["contains_class_c"] is False

        with pytest.raises(ValidationError, match="mandatory"):
            await create_tier2_archive(
                server_id="srv-1",
                server_dir=server_dir,
                backup_id="b-noenc-s3",
                storage=s3_store,
                archive_format="tar.gz",
                encrypt=False,
            )


# ---------------------------------------------------------------------------
# Archive Matrix, Backup Saga, Baseline Hook, Tasks, & Streaming
# ---------------------------------------------------------------------------


def _seed_matrix_dir(server_dir: Path) -> None:
    _write_text(server_dir, "world/region/r.0.0.mca", "world-region")
    _write_text(server_dir, "world/playerdata/abc.dat", "world-pd")
    _write_text(server_dir, "world_nether/DIM-1/r.0.0.mca", "nether-region")
    _write_text(server_dir, "world_nether/playerdata/abc.dat", "nether-pd")
    _write_text(server_dir, "world_the_end/DIM1/r.0.0.mca", "end-region")
    _write_text(server_dir, "world_the_end/playerdata/abc.dat", "end-pd")
    _write_text(server_dir, "plugins/essentials.jar", "plugin-jar")
    for name in CONFIG_FILES:
        _write_text(server_dir, name, f"cfg:{name}")


def _archive_names(
    server_dir: Path, backup_type: BackupType, primary_world: str = "world"
) -> list[str]:
    saga = BackupSaga(SagaOrchestrator())
    tar_path = str(server_dir / "out.tar.gz")
    saga._write_tar(tar_path, str(server_dir), primary_world=primary_world, backup_type=backup_type)
    with tarfile.open(tar_path, "r:gz") as tar:
        return tar.getnames()


class TestArchiveMatrix:
    @pytest.mark.parametrize(
        ("backup_type", "expected_dims", "expect_plugins", "expect_config", "expect_pd_namespace"),
        [
            (BackupType.FULL, {"world", "world_nether", "world_the_end"}, True, True, set()),
            (BackupType.WORLDS, {"world", "world_nether", "world_the_end"}, False, False, set()),
            (
                BackupType.WORLD,
                {"world"},
                False,
                False,
                {
                    "mcs_playerdata/world_nether/playerdata",
                    "mcs_playerdata/world_the_end/playerdata",
                },
            ),
            (
                BackupType.NETHER,
                {"world_nether"},
                False,
                False,
                {"mcs_playerdata/world/playerdata", "mcs_playerdata/world_the_end/playerdata"},
            ),
            (
                BackupType.END,
                {"world_the_end"},
                False,
                False,
                {"mcs_playerdata/world/playerdata", "mcs_playerdata/world_nether/playerdata"},
            ),
            (BackupType.PLUGINS, set(), True, False, set()),
            (BackupType.CONFIG, set(), False, True, set()),
        ],
    )
    def test_archive_contents_by_backup_type(
        self,
        tmp_path: Path,
        backup_type: BackupType,
        expected_dims: set[str],
        expect_plugins: bool,
        expect_config: bool,
        expect_pd_namespace: set[str],
    ) -> None:
        server_dir = tmp_path / "server"
        _seed_matrix_dir(server_dir)
        names = _archive_names(server_dir, backup_type)

        assert {
            n for n in names if n in {"world", "world_nether", "world_the_end"}
        } == expected_dims
        assert ("plugins" in names) is expect_plugins
        config_present = {n for n in names if n in CONFIG_FILES}
        assert bool(config_present) is expect_config
        if expect_config:
            assert config_present == set(CONFIG_FILES)
        pd_namespace = {
            "/".join(n.split("/")[:3]) for n in names if n.startswith("mcs_playerdata/")
        }
        assert pd_namespace == expect_pd_namespace

    def test_archive_edge_cases_and_custom_primary_world(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        _seed_matrix_dir(server_dir)
        world_names = _archive_names(server_dir, BackupType.WORLD)
        assert "world/playerdata/abc.dat" in world_names
        assert "mcs_playerdata/world/playerdata" not in world_names

        # Missing optional dimensions skipped for WORLD, required for NETHER/END
        only_world = tmp_path / "only_world"
        _write_text(only_world, "world/level.dat", "only-overworld")
        assert "world" in _archive_names(only_world, BackupType.WORLD)
        with pytest.raises(FileNotFoundError, match="world_nether"):
            _archive_names(only_world, BackupType.NETHER)
        with pytest.raises(FileNotFoundError, match="world_the_end"):
            _archive_names(only_world, BackupType.END)

        # Plugins/Config work without world folders
        plugins_only = tmp_path / "plugins_only"
        _write_text(plugins_only, "plugins/essentials.jar", "jar")
        assert "plugins" in _archive_names(plugins_only, BackupType.PLUGINS)

        cfg_only = tmp_path / "cfg_only"
        for name in CONFIG_FILES:
            _write_text(cfg_only, name, f"cfg:{name}")
        assert set(CONFIG_FILES) <= set(_archive_names(cfg_only, BackupType.CONFIG))

        # Custom primary world
        custom = tmp_path / "custom"
        _write_text(custom, "mypvp/level.dat", "pvp")
        _write_text(custom, "mypvp_nether/playerdata/x.dat", "npd")
        custom_names = _archive_names(custom, BackupType.WORLD, primary_world="mypvp")
        assert "mypvp" in custom_names
        assert "mcs_playerdata/mypvp_nether/playerdata" in custom_names


class _FakeConsoleProvider:
    def __init__(self, console_responses: list[list[str]]) -> None:
        self.commands: list[str] = []
        self._responses = list(console_responses)

    async def execute_command(self, _handle, command: str) -> str:
        self.commands.append(command)
        return ""

    async def console(self, _handle, tail: int = 100) -> list[str]:  # noqa: ARG002
        return self._responses.pop(0) if self._responses else []


class TestBackupSagaAndStreaming:
    def _seed_world(self, server_dir: str) -> None:
        world_dir = Path(server_dir) / "world" / "region"
        world_dir.mkdir(parents=True, exist_ok=True)
        (world_dir / "r.0.0.mca").write_bytes(b"\x00" * 4096)
        (Path(server_dir) / "server.properties").write_text("motd=saga\n", encoding="utf-8")
        (Path(server_dir) / "eula.txt").write_text("eula=true\n", encoding="utf-8")

    async def test_saga_compresses_encrypts_uploads_and_verifies(self, tmp_path: Path) -> None:
        server_dir = str(tmp_path / "server")
        self._seed_world(server_dir)
        server_id = ServerId(uuid.uuid4().hex)
        backup_id = BackupJobId()
        storage = LocalStorage(str(tmp_path / "backups"))
        encryption = BackupEncryption(key=os.urandom(32))

        async with database.session_factory() as session:
            await SQLServerRepository(session).save(_build_server(server_id, server_dir))
            await session.commit()
        await _seed_job(str(backup_id), str(server_id), completed=False)

        await BackupSaga(SagaOrchestrator()).execute(
            backup_id=backup_id, server_id=server_id, storage=storage, encryption=encryption
        )

        async with database.session_factory() as session:
            job = await SQLBackupRepository(session).get_job(backup_id)
        assert job.status == BackupStatus.COMPLETED
        assert job.storage_path == f"{backup_id}.tar.gz.enc"
        artifact = await storage.read(job.storage_path)
        assert hashlib.sha256(artifact).hexdigest() == job.checksum
        with tarfile.open(fileobj=io.BytesIO(encryption.decrypt(artifact)), mode="r:gz") as tar:
            assert {"world", "world/region/r.0.0.mca", "server.properties", "eula.txt"} <= set(
                tar.getnames()
            )

    async def test_saga_full_allows_missing_world_while_world_backup_fails(
        self, tmp_path: Path
    ) -> None:
        server_dir = str(tmp_path / "server")
        Path(server_dir).mkdir(parents=True, exist_ok=True)
        (Path(server_dir) / "server.properties").write_text("motd=no world\n", encoding="utf-8")
        server_id = ServerId(uuid.uuid4().hex)
        storage = LocalStorage(str(tmp_path / "backups"))
        encryption = BackupEncryption(key=os.urandom(32))

        async with database.session_factory() as session:
            await SQLServerRepository(session).save(_build_server(server_id, server_dir))
            await session.commit()

        full_id = BackupJobId()
        await _seed_job(str(full_id), str(server_id), completed=False)
        await BackupSaga(SagaOrchestrator()).execute(
            backup_id=full_id,
            server_id=server_id,
            storage=storage,
            encryption=encryption,
            backup_type=BackupType.FULL,
        )
        async with database.session_factory() as session:
            assert (
                await SQLBackupRepository(session).get_job(full_id)
            ).status == BackupStatus.COMPLETED

        world_id = BackupJobId()
        async with database.session_factory() as session:
            job = BackupJob.create(
                backup_id=world_id, server_id=server_id, backup_type=BackupType.WORLD
            )
            await SQLBackupRepository(session).save_job(job)
            await session.commit()
        await BackupSaga(SagaOrchestrator()).execute(
            backup_id=world_id,
            server_id=server_id,
            storage=storage,
            encryption=encryption,
            backup_type=BackupType.WORLD,
        )
        async with database.session_factory() as session:
            failed = await SQLBackupRepository(session).get_job(world_id)
            assert failed.status == BackupStatus.FAILED and failed.size_bytes == 0
        assert not await storage.exists(f"{world_id}.tar.gz.enc")

    async def test_save_all_confirmation_ignores_baseline_and_fails_on_timeout(
        self, tmp_path: Path
    ) -> None:
        server_dir = str(tmp_path / "server")
        self._seed_world(server_dir)
        server_id = ServerId(uuid.uuid4().hex)
        storage = LocalStorage(str(tmp_path / "backups"))

        async with database.session_factory() as session:
            await SQLServerRepository(session).save(
                _build_server(server_id, server_dir, running=True)
            )
            await session.commit()

        # Baseline offset test
        saga = BackupSaga(MagicMock())
        provider = AsyncMock()
        call_count = 0

        async def mock_console(_handle, tail=200):  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ["Starting save", "Saved the game", "Log after baseline"]
            return ["Starting save", "Saved the game", "Log after baseline", "Saved the game"]

        provider.console = mock_console
        await saga._wait_for_save_confirmed(
            BackupJobId(),
            ServerId("s1"),
            provider,
            MagicMock(),
            baseline_lines=["Starting save", "Saved the game"],
        )
        assert call_count == 2

        # Confirmed save proceeds
        ok_id = BackupJobId()
        await _seed_job(str(ok_id), str(server_id), completed=False)
        fake_ok = _FakeConsoleProvider(
            [
                ["[Server thread/INFO]: Saving chunks for level 'world'/overworld"],
                ["[Server thread/INFO]: Saved the game"],
            ]
        )
        with patch("app.modules.server.infrastructure.providers.provider_factory") as mock_factory:
            mock_factory.get.return_value = fake_ok
            await BackupSaga(SagaOrchestrator()).execute(
                backup_id=ok_id,
                server_id=server_id,
                storage=storage,
                encryption=BackupEncryption(key=os.urandom(32)),
            )
        assert fake_ok.commands == ["save-all"]
        async with database.session_factory() as session:
            assert (
                await SQLBackupRepository(session).get_job(ok_id)
            ).status == BackupStatus.COMPLETED

        # Timeout marks job failed
        timeout_id = BackupJobId()
        await _seed_job(str(timeout_id), str(server_id), completed=False)
        fake_timeout = _FakeConsoleProvider(
            [["[Server thread/INFO]: Saving chunks for level 'world'/overworld"]]
        )
        with (
            patch("app.modules.server.infrastructure.providers.provider_factory") as mock_factory,
            patch("app.services.backup_orchestrator.SAVE_ALL_CONFIRMATION_TIMEOUT_S", 0.3),
            patch("app.services.backup_orchestrator.SAVE_ALL_POLL_INTERVAL_S", 0.05),
        ):
            mock_factory.get.return_value = fake_timeout
            await BackupSaga(SagaOrchestrator()).execute(
                backup_id=timeout_id,
                server_id=server_id,
                storage=storage,
                encryption=BackupEncryption(key=os.urandom(32)),
            )
        async with database.session_factory() as session:
            job = await SQLBackupRepository(session).get_job(timeout_id)
            assert job.status == BackupStatus.FAILED and "save_world" in job.error_message

    async def test_write_tar_runs_off_event_loop_concurrently(self) -> None:
        orchestrator = BackupSaga(MagicMock())
        concurrent_task_ran = False

        async def bg() -> None:
            nonlocal concurrent_task_ran
            await asyncio.sleep(0.01)
            concurrent_task_ran = True

        def slow_tar(tar_path: str, *_args: Any, **_kwargs: Any) -> None:
            import time

            time.sleep(0.05)
            Path(tar_path).write_bytes(b"dummy-tar-content")

        with (
            patch.object(
                orchestrator, "_resolve_server_dir", AsyncMock(return_value=("/tmp/srv", "world"))
            ),
            patch.object(orchestrator, "_write_tar", side_effect=slow_tar),
        ):
            compress_fn = orchestrator._compress(
                BackupJobId("b1234567-89ab-cdef-0123-456789abcdef"), ServerId("srv-test-1")
            )
            await asyncio.gather(compress_fn(), bg())

        assert concurrent_task_ran is True
        orchestrator._cleanup_temp_dir()

    async def test_encrypt_and_upload_use_chunked_reads(self) -> None:
        orchestrator = BackupSaga(MagicMock())
        backup_id = BackupJobId("b1234567-89ab-cdef-0123-456789abcdef")
        encryption = BackupEncryption()
        temp_dir = tempfile.mkdtemp()
        tar_path = os.path.join(temp_dir, "test.tar.gz")
        Path(tar_path).write_bytes(b"X" * (192 * 1024))
        orchestrator._temp_dir = temp_dir
        orchestrator._tar_path = tar_path

        read_calls: list[int] = []
        orig_open = open

        def tracked_open(file, mode="r", *args, **kwargs):
            f = orig_open(file, mode, *args, **kwargs)
            if "rb" in mode:
                orig_read = f.read

                def chunked_read(size=-1):
                    read_calls.append(size)
                    return orig_read(size)

                f.read = chunked_read
            return f

        try:
            with patch("builtins.open", side_effect=tracked_open):
                await orchestrator._encrypt(backup_id, encryption)()
            assert len([s for s in read_calls if s == 64 * 1024]) >= 3

            read_calls.clear()
            storage = MagicMock(write=AsyncMock())
            with patch("builtins.open", side_effect=tracked_open):
                await orchestrator._upload(backup_id, storage, encryption)()
            assert len([s for s in read_calls if s == 64 * 1024]) >= 3
            assert storage.write.called
        finally:
            orchestrator._cleanup_temp_dir()


# ---------------------------------------------------------------------------
# Backup Task, Baseline Hook, & Tier Routing
# ---------------------------------------------------------------------------


@dataclass
class _RecordedJob:
    backup_id: str
    status: str = "pending"
    error_message: str = ""

    def mark_failed(self, reason: str) -> None:
        self.status = "failed"
        self.error_message = reason

    def mark_failed_timeout(self, reason: str) -> None:
        self.status = "failed_timeout"
        self.error_message = reason


class _FakeJobRepo:
    def __init__(self, job: _RecordedJob) -> None:
        self.job = job
        self.saved_jobs: list[_RecordedJob] = []

    async def get_job(self, _backup_id: BackupJobId) -> _RecordedJob:
        return self.job

    async def save_job(self, job: _RecordedJob) -> None:
        self.saved_jobs.append(job)


class _FakeUOW:
    def __init__(self, repo: _FakeJobRepo) -> None:
        self.session = MagicMock()
        self.repo = repo
        self.committed = False

    async def __aenter__(self) -> _FakeUOW:
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True


class TestBackupTaskAndBaselineHook:
    async def test_backup_task_requires_server_id_and_backup_id(self) -> None:
        with pytest.raises(KeyError):
            await run_backup_task({})
        with pytest.raises(KeyError):
            await run_backup_task({"server_id": "srv-1"})

    async def test_baseline_adoption_runs_before_saga_and_logs_warnings(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        events: list[str] = []

        async def fake_adopt(_server_id: str) -> BaselineAdoptionResult:
            events.append("adopt")
            return BaselineAdoptionResult(
                status="created",
                files_count=3,
                cas_ingested=3,
                quarantined=("config/evil.jar", "mods/suspicious.jar"),
            )

        async def fake_execute(*_args: Any, **_kwargs: Any) -> None:
            events.append("execute")

        with (
            caplog.at_level(logging.INFO),
            patch(
                "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                side_effect=fake_adopt,
            ),
            patch.object(BackupSaga, "execute", side_effect=fake_execute),
            patch("app.tasks.definitions.backup_task.build_storage_backend"),
            patch("app.tasks.definitions.backup_task.build_backup_encryption"),
        ):
            res = await run_backup_task({"backup_id": "b-1", "server_id": "srv-1"})

        assert events == ["adopt", "execute"]
        assert res == {"backup_id": "b-1", "server_id": "srv-1"}
        assert any(
            "status=created" in r.message and "files_count=3" in r.message for r in caplog.records
        )
        warn_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("config/evil.jar" in m for m in warn_msgs)
        assert any("mods/suspicious.jar" in m for m in warn_msgs)

    async def test_baseline_adoption_cancelled_and_failure_modes(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 1. Cancelled adoption marks failed_timeout
        job_cancel = _RecordedJob(backup_id="b-cancel")
        repo_cancel = _FakeJobRepo(job_cancel)
        uow_cancel = _FakeUOW(repo_cancel)
        clear_mock = MagicMock()
        saga_mock = AsyncMock()
        with (
            patch(
                "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                AsyncMock(side_effect=ValidationError("Adoption aborted")),
            ),
            patch.object(BackupSaga, "execute", saga_mock),
            patch("app.tasks.definitions.backup_task.build_storage_backend"),
            patch("app.tasks.definitions.backup_task.build_backup_encryption"),
            patch("app.tasks.definitions.backup_task.UnitOfWork", return_value=uow_cancel),
            patch(
                "app.tasks.definitions.backup_task.SQLBackupRepository", return_value=repo_cancel
            ),
            patch("app.tasks.definitions.backup_task.is_backup_cancelled", return_value=True),
            patch("app.tasks.definitions.backup_task.clear_cancelled_backup", clear_mock),
            pytest.raises(ValidationError, match="Adoption aborted"),
        ):
            await run_backup_task({"backup_id": "b-cancel", "server_id": "srv-cancel"})
        saga_mock.assert_not_called()
        assert job_cancel.status == "failed_timeout" and uow_cancel.committed is True
        clear_mock.assert_called_once_with("b-cancel")

        # 2. ValidationError / CasError / OSError fail closed
        for err_cls, msg in [
            (ValidationError, "Tree scan truncated"),
            (CasError, "CAS corrupt blob"),
            (OSError, "Disk failure"),
        ]:
            job = _RecordedJob(backup_id="b-fail")
            repo = _FakeJobRepo(job)
            uow = _FakeUOW(repo)
            with (
                patch(
                    "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                    AsyncMock(side_effect=err_cls(msg)),
                ),
                patch.object(BackupSaga, "execute", AsyncMock()) as s_mock,
                patch("app.tasks.definitions.backup_task.build_storage_backend"),
                patch("app.tasks.definitions.backup_task.build_backup_encryption"),
                patch("app.tasks.definitions.backup_task.UnitOfWork", return_value=uow),
                patch("app.tasks.definitions.backup_task.SQLBackupRepository", return_value=repo),
                pytest.raises(err_cls, match=msg),
            ):
                await run_backup_task({"backup_id": "b-fail", "server_id": "srv-fail"})
            s_mock.assert_not_called()
            assert job.status == "failed" and uow.committed is True

        # 3. Unsupported platform continues with warning; skipped non-simple continues
        with (
            caplog.at_level(logging.WARNING),
            patch(
                "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                AsyncMock(side_effect=CasUnsupportedPlatformError("POSIX only")),
            ),
            patch.object(BackupSaga, "execute", AsyncMock()) as s_mock,
            patch("app.tasks.definitions.backup_task.build_storage_backend"),
            patch("app.tasks.definitions.backup_task.build_backup_encryption"),
        ):
            res = await run_backup_task({"backup_id": "b-win", "server_id": "srv-win"})
        assert res == {"backup_id": "b-win", "server_id": "srv-win"}
        s_mock.assert_awaited_once()
        assert any("adoption_skipped_unsupported_platform" in r.message for r in caplog.records)

    async def test_run_backup_task_tier2_and_tier1_routing_and_activity_labels(
        self, tmp_path: Path
    ) -> None:
        server_dir = tmp_path / "srv-1"
        (server_dir / "world").mkdir(parents=True)
        (server_dir / "world" / "level.dat").write_bytes(b"world")
        (server_dir / "server.properties").write_text("motd=Test\n", encoding="utf-8")

        async with database.session_factory() as session:
            session.add(
                ServerModel(
                    id="srv-1",
                    name="Srv 1",
                    server_type="vanilla",
                    minecraft_version="1.21.1",
                    port=25565,
                    memory_min_mb=512,
                    memory_max_mb=1024,
                    root_path=str(server_dir),
                    working_directory=".",
                    provider="docker",
                    location_type="docker",
                    mode="simple",
                )
            )
            await session.commit()
        await _seed_job("b-t2", "srv-1", tier=BackupTier.TIER_2, completed=False)
        await _seed_job("b-t1-ok", "srv-1", tier=BackupTier.TIER_1, completed=False)
        await _seed_job("b-t1-fail", "srv-missing", tier=BackupTier.TIER_1, completed=False)

        fake_settings = SimpleNamespace(
            backup_storage_path=str(tmp_path / "backup_storage"),
            backup_encryption_key_path=str(tmp_path / "backup.key"),
            storage_backend="local",
            host_state_dir=str(tmp_path / "host_state"),
            host_state_host_dir="",
            host_data_dir="",
            servers_data_dir=str(tmp_path / "servers"),
        )
        bus = EventBus()
        published: list[DomainEvent] = []

        class _Capture(EventHandler):
            async def handle(self, event: DomainEvent) -> None:
                published.append(event)

        cap = _Capture()
        bus.subscribe("BackupCompletedEvent", cap)
        bus.subscribe("BackupFailedEvent", cap)

        with (
            patch(
                "app.tasks.definitions.backup_task.ConfigFactory.global_settings",
                return_value=fake_settings,
            ),
            patch("app.tasks.definitions.backup_task.get_optional_event_bus", return_value=bus),
            patch(
                "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
                AsyncMock(
                    return_value=BaselineAdoptionResult(
                        status="created", files_count=1, cas_ingested=0
                    )
                ),
            ) as mock_adopt,
        ):
            res_t2 = await run_backup_task(
                {
                    "backup_id": "b-t2",
                    "server_id": "srv-1",
                    "tier": BackupTier.TIER_2.value,
                    "archive_format": "tar.gz",
                    "encrypt": False,
                }
            )
            mock_adopt.assert_awaited_once_with("srv-1")
            assert res_t2["backup_id"] == "b-t2"

            res_t1 = await run_backup_task(
                {
                    "backup_id": "b-t1-ok",
                    "server_id": "srv-1",
                    "tier": BackupTier.TIER_1.value,
                    "two_tier": True,
                }
            )
            assert res_t1 == {"backup_id": "b-t1-ok", "server_id": "srv-1"}
            assert (tmp_path / "backup_storage" / "tier1" / "srv-1" / "b-t1-ok").is_dir()
            assert any(isinstance(e, BackupCompletedEvent) for e in published)

            with pytest.raises(NotFoundError):
                await run_backup_task(
                    {
                        "backup_id": "b-t1-fail",
                        "server_id": "srv-missing",
                        "tier": BackupTier.TIER_1.value,
                        "two_tier": True,
                    }
                )
            assert any(isinstance(e, BackupFailedEvent) for e in published)

        sub = ActivityEventSubscriber(AsyncMock())
        msg1, act1 = sub._resolve_summary_and_type(
            BackupStartedEvent(backup_id="12345678", server_id="srv-1", tier="tier_1"),
            "BackupStartedEvent",
        )
        msg2, act2 = sub._resolve_summary_and_type(
            BackupCompletedEvent(
                backup_id="12345678", server_id="srv-1", size_bytes=10, checksum="aa", tier="tier_2"
            ),
            "BackupCompletedEvent",
        )
        assert act1 == "backup.started" and "Tier-1" in msg1
        assert act2 == "backup.completed" and "Tier-2" in msg2
