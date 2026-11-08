"""Tests for promote atomicity, stop confirmation gating, rollback journal, and restore lock guard.

Covers Batch 3 of SPEC-2026-11-08-SERVER-LIFECYCLE-HARDENING-01.md.
"""
from __future__ import annotations

import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.command_bus import CommandBus, CommandResult
from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.backup.application.commands.restore_backup import (
    RestoreBackupCommand,
    RestoreBackupHandler,
)
from app.modules.backup.domain.aggregate import BackupJob
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.server.application.commands.start_server import StartServerCommand
from app.modules.server.application.commands.stop_server import StopServerCommand
from app.modules.server.application.lifecycle_lock import ServerLifecycleLockTimeoutError
from app.modules.server.domain.aggregate import (
    Server,
    ServerStatus,
)
from app.modules.server.domain.repository import ServerRepository
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
from app.modules.server.infrastructure.fs import local_fs
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import BackupJobId, MinecraftVersion, ServerId
from app.modules.versioning.application.commands.promote_commit import (
    PromoteCommitCommand,
    PromoteCommitHandler,
    _is_stop_confirmed,
)
from app.modules.versioning.domain.entities import (
    ServerBranch,
    ServerCommit,
    ServerTestRun,
    ServerWorldSnapshot,
)
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import CommitManifest, TestRunStatus
from app.modules.versioning.infrastructure.test_runner import TestExecutionRunner


class InMemoryVersioningRepository(VersioningRepository):
    def __init__(self) -> None:
        self.branches: dict[str, ServerBranch] = {}
        self.commits: dict[str, ServerCommit] = {}
        self.snapshots: dict[str, ServerWorldSnapshot] = {}
        self.test_runs: dict[str, ServerTestRun] = {}

    async def get_branch(self, branch_id: str) -> ServerBranch | None:
        return self.branches.get(branch_id)

    async def get_branch_by_name(self, server_id: str, name: str) -> ServerBranch | None:
        for b in self.branches.values():
            if b.server_id == server_id and b.name == name:
                return b
        return None

    async def list_branches(self, server_id: str) -> list[ServerBranch]:
        return [b for b in self.branches.values() if b.server_id == server_id]

    async def save_branch(self, branch: ServerBranch) -> ServerBranch:
        self.branches[branch.id] = branch
        return branch

    async def advance_branch_head_optimistic(
        self, branch_id: str, new_head: str, expected_head: str | None
    ) -> bool:
        branch = self.branches.get(branch_id)
        if branch is None or branch.head_commit_id != expected_head:
            return False
        branch.advance_head(new_head)
        return True

    async def get_commit(self, commit_id: str) -> ServerCommit | None:
        return self.commits.get(commit_id)

    async def list_commits(
        self, server_id: str, branch_id: str | None = None, limit: int = 50
    ) -> list[ServerCommit]:
        _ = branch_id
        res = [c for c in self.commits.values() if c.server_id == server_id]
        return res[:limit]

    async def save_commit(self, commit: ServerCommit) -> ServerCommit:
        self.commits[commit.id] = commit
        return commit

    async def get_snapshot(self, snapshot_id: str) -> ServerWorldSnapshot | None:
        return self.snapshots.get(snapshot_id)

    async def save_snapshot(self, snapshot: ServerWorldSnapshot) -> ServerWorldSnapshot:
        self.snapshots[snapshot.id] = snapshot
        return snapshot

    async def get_test_run(self, test_id: str) -> ServerTestRun | None:
        return self.test_runs.get(test_id)

    async def get_active_test_run_for_server(self, server_id: str) -> ServerTestRun | None:
        for r in self.test_runs.values():
            if r.server_id == server_id and r.status in (
                TestRunStatus.QUEUED,
                TestRunStatus.RUNNING,
            ):
                return r
        return None

    async def list_test_runs(self, server_id: str, limit: int = 20) -> list[ServerTestRun]:
        res = [r for r in self.test_runs.values() if r.server_id == server_id]
        return res[:limit]

    async def save_test_run(self, test_run: ServerTestRun) -> ServerTestRun:
        self.test_runs[test_run.id] = test_run
        return test_run


def test_is_stop_confirmed_contract() -> None:
    # 1. None or failure
    assert _is_stop_confirmed(None) is False
    assert _is_stop_confirmed(CommandResult(success=False)) is False

    # 2. Non-dict or empty data
    assert _is_stop_confirmed(CommandResult(success=True, data=None)) is False
    assert _is_stop_confirmed(CommandResult(success=True, data={})) is False

    # 3. Explicit False
    assert _is_stop_confirmed(
        CommandResult(success=True, data={"status": "stopped", "stop_confirmed": False})
    ) is False

    # 4. Warnings or provider errors
    assert _is_stop_confirmed(
        CommandResult(
            success=True,
            data={"status": "stopped", "stop_confirmed": True, "warnings": ["port open"]},
        )
    ) is False
    assert _is_stop_confirmed(
        CommandResult(
            success=True,
            data={"status": "stopped", "stop_confirmed": True, "provider_errors": ["kill failed"]},
        )
    ) is False

    # 5. Confirmed stopped
    assert _is_stop_confirmed(
        CommandResult(success=True, data={"status": "stopped", "stop_confirmed": True})
    ) is True

    # 6. Legacy mock with status=="stopped" and no errors
    assert _is_stop_confirmed(
        CommandResult(success=True, data={"status": "stopped"})
    ) is True

    # 7. Non-stopped status
    assert _is_stop_confirmed(
        CommandResult(success=True, data={"status": "running"})
    ) is False
    assert _is_stop_confirmed(
        CommandResult(success=True, data={"status": "stopping"})
    ) is False


@pytest.mark.asyncio
async def test_promote_aborts_when_stop_not_confirmed() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "srv"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("motd=ProductionRunning\n", encoding="utf-8")

        test_dir = srv_dir / ".onx" / "tests" / "t-stop-fail"
        test_dir.mkdir(parents=True)
        (test_dir / "server.properties").write_text("motd=PromotedTarget\n", encoding="utf-8")

        mock_server = MagicMock(spec=Server)
        mock_server.id = ServerId("srv-stop-fail")
        mock_server.status = ServerStatus.RUNNING
        mock_server.deployment = ServerDeployment(root_path=str(srv_dir), working_directory=".")

        server_repo = AsyncMock(spec=ServerRepository)
        server_repo.get.return_value = mock_server

        v_repo = InMemoryVersioningRepository()
        manifest = CommitManifest(
            server_type="vanilla",
            minecraft_version="1.21.1",
            configs={"server.properties": "motd=PromotedTarget\n"},
        )
        commit = ServerCommit(
            id="c-stop-fail", server_id="srv-stop-fail", message="Test commit", manifest=manifest
        )
        await v_repo.save_commit(commit)

        test_run = ServerTestRun(
            id="t-stop-fail",
            server_id="srv-stop-fail",
            commit_id="c-stop-fail",
            status=TestRunStatus.PASSED,
        )
        await v_repo.save_test_run(test_run)

        command_bus = AsyncMock(spec=CommandBus)
        test_runner = AsyncMock(spec=TestExecutionRunner)

        # 1. Stop returns unconfirmed result (with warnings)
        command_bus.send.return_value = CommandResult(
            success=True,
            data={"status": "stopping", "stop_confirmed": False, "warnings": ["port occupied"]},
        )

        handler = PromoteCommitHandler(
            server_repo=server_repo,
            versioning_repo=v_repo,
            command_bus=command_bus,
            test_runner=test_runner,
        )

        result = await handler.handle(
            PromoteCommitCommand(server_id="srv-stop-fail", test_id="t-stop-fail")
        )

        assert result.success is False
        assert result.error_code == "PROMOTE_STOP_NOT_CONFIRMED"
        assert result.details["stop_result"]["stop_confirmed"] is False

        # Production directory untouched
        assert (srv_dir / "server.properties").read_text(
            encoding="utf-8"
        ) == "motd=ProductionRunning\n"
        # Test directory untouched and cleanup NOT called
        assert (test_dir / "server.properties").exists()
        test_runner.cleanup_test.assert_not_called()

        # 2. Server in STOPPING state and stop command raises exception
        mock_server.status = ServerStatus.STOPPING
        command_bus.send.side_effect = Exception("Docker daemon connection lost")

        result2 = await handler.handle(
            PromoteCommitCommand(server_id="srv-stop-fail", test_id="t-stop-fail")
        )
        assert result2.success is False
        assert result2.error_code == "PROMOTE_STOP_NOT_CONFIRMED"
        assert (srv_dir / "server.properties").read_text(
            encoding="utf-8"
        ) == "motd=ProductionRunning\n"
        test_runner.cleanup_test.assert_not_called()


@pytest.mark.asyncio
async def test_promote_midflight_config_failure_rolls_back_and_restarts() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "srv"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("motd=ProductionOld\n", encoding="utf-8")
        (srv_dir / "config").mkdir()
        (srv_dir / "config" / "settings.json").write_text('{"old": true}\n', encoding="utf-8")

        test_dir = srv_dir / ".onx" / "tests" / "t-cfg-fail"
        test_dir.mkdir(parents=True)
        (test_dir / "server.properties").write_text("motd=PromotedNew\n", encoding="utf-8")

        mock_server = MagicMock(spec=Server)
        mock_server.id = ServerId("srv-cfg-fail")
        mock_server.status = ServerStatus.RUNNING
        mock_server.deployment = ServerDeployment(root_path=str(srv_dir), working_directory=".")

        server_repo = AsyncMock(spec=ServerRepository)
        server_repo.get.return_value = mock_server

        v_repo = InMemoryVersioningRepository()
        manifest = CommitManifest(
            server_type="vanilla",
            minecraft_version="1.21.1",
            configs={
                "server.properties": "motd=PromotedNew\n",
                "config/settings.json": '{"new": true}\n',
                "ops.json": '[{"name": "admin"}]\n',
            },
        )
        commit = ServerCommit(
            id="c-cfg-fail", server_id="srv-cfg-fail", message="Cfg fail commit", manifest=manifest
        )
        await v_repo.save_commit(commit)

        test_run = ServerTestRun(
            id="t-cfg-fail",
            server_id="srv-cfg-fail",
            commit_id="c-cfg-fail",
            status=TestRunStatus.PASSED,
        )
        await v_repo.save_test_run(test_run)

        command_bus = AsyncMock(spec=CommandBus)
        test_runner = AsyncMock(spec=TestExecutionRunner)

        # Stop succeeds with confirmation; start succeeds on rollback restart
        async def mock_bus_send(cmd):
            if isinstance(cmd, StopServerCommand):
                return CommandResult(
                    success=True,
                    data={"status": "stopped", "stop_confirmed": True, "warnings": []},
                )
            if isinstance(cmd, StartServerCommand):
                return CommandResult(success=True, data={"status": "running"})
            return CommandResult(success=True)

        command_bus.send.side_effect = mock_bus_send

        # Simulate failure writing second file config/settings.json
        orig_write = local_fs.write_text_atomic
        fake_fs = MagicMock(spec=local_fs)

        def selective_write(path: str, content: str, encoding: str = "utf-8"):
            if "settings.json" in path:
                raise OSError("Simulated disk write failure on settings.json")
            orig_write(path, content, encoding)

        fake_fs.write_text_atomic.side_effect = selective_write

        handler = PromoteCommitHandler(
            server_repo=server_repo,
            versioning_repo=v_repo,
            command_bus=command_bus,
            test_runner=test_runner,
            fs=fake_fs,
        )

        result = await handler.handle(
            PromoteCommitCommand(server_id="srv-cfg-fail", test_id="t-cfg-fail")
        )

        assert result.success is False
        assert result.error_code == "PROMOTE_SWAP_ROLLED_BACK"
        assert result.details["rolled_back"] is True
        assert result.details["restart_attempted"] is True
        assert result.details["restart_ok"] is True

        # Verify rollback to byte-identical state
        assert (srv_dir / "server.properties").read_text(
            encoding="utf-8"
        ) == "motd=ProductionOld\n"
        assert (srv_dir / "config" / "settings.json").read_text(
            encoding="utf-8"
        ) == '{"old": true}\n'
        assert not (srv_dir / "ops.json").exists()

        # Test environment preserved
        test_runner.cleanup_test.assert_not_called()

        # StartServerCommand was dispatched to bring server back online
        assert any(
            isinstance(call.args[0], StartServerCommand) for call in command_bus.send.call_args_list
        )


@pytest.mark.asyncio
async def test_promote_midflight_mods_or_world_failure_rolls_back_and_preserves_test_dir() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "srv"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("motd=ProdOld\n", encoding="utf-8")

        # Live mods
        live_mods = srv_dir / "mods"
        live_mods.mkdir()
        (live_mods / "old_mod.jar").write_bytes(b"old-mod-bytes")

        # Live worlds
        live_world = srv_dir / "world"
        live_world.mkdir()
        (live_world / "level.dat").write_text("live-overworld", encoding="utf-8")

        live_nether = srv_dir / "world_nether"
        live_nether.mkdir()
        (live_nether / "level.dat").write_text("live-nether", encoding="utf-8")

        # Test environment
        test_dir = srv_dir / ".onx" / "tests" / "t-world-fail"
        test_dir.mkdir(parents=True)
        test_mods = test_dir / "mods"
        test_mods.mkdir()
        (test_mods / "new_mod.jar").write_bytes(b"new-mod-bytes")

        test_world = test_dir / "world"
        test_world.mkdir()
        (test_world / "level.dat").write_text("test-overworld", encoding="utf-8")

        test_nether = test_dir / "world_nether"
        test_nether.mkdir()
        (test_nether / "level.dat").write_text("test-nether", encoding="utf-8")

        mock_server = MagicMock(spec=Server)
        mock_server.id = ServerId("srv-world-fail")
        mock_server.status = ServerStatus.RUNNING
        mock_server.deployment = ServerDeployment(root_path=str(srv_dir), working_directory=".")

        server_repo = AsyncMock(spec=ServerRepository)
        server_repo.get.return_value = mock_server

        v_repo = InMemoryVersioningRepository()
        manifest = CommitManifest(
            server_type="vanilla",
            minecraft_version="1.21.1",
            configs={"server.properties": "motd=PromotedTarget\n"},
        )
        commit = ServerCommit(
            id="c-world-fail",
            server_id="srv-world-fail",
            message="World commit",
            manifest=manifest,
        )
        await v_repo.save_commit(commit)

        test_run = ServerTestRun(
            id="t-world-fail",
            server_id="srv-world-fail",
            commit_id="c-world-fail",
            status=TestRunStatus.PASSED,
        )
        await v_repo.save_test_run(test_run)

        command_bus = AsyncMock(spec=CommandBus)
        test_runner = AsyncMock(spec=TestExecutionRunner)

        async def mock_bus_send(cmd):
            if isinstance(cmd, StopServerCommand):
                return CommandResult(
                    success=True,
                    data={"status": "stopped", "stop_confirmed": True, "warnings": []},
                )
            if isinstance(cmd, StartServerCommand):
                return CommandResult(success=True, data={"status": "running"})
            return CommandResult(success=True)

        command_bus.send.side_effect = mock_bus_send

        # Simulate failure during world_nether swap
        real_replace = os.replace

        def selective_replace(src, dst):
            if "world_nether" in str(dst) and "staged" in str(src):
                raise OSError("Simulated atomic swap failure on world_nether")
            real_replace(src, dst)

        with patch("os.replace", side_effect=selective_replace):
            handler = PromoteCommitHandler(
                server_repo=server_repo,
                versioning_repo=v_repo,
                command_bus=command_bus,
                test_runner=test_runner,
            )

            result = await handler.handle(
                PromoteCommitCommand(
                    server_id="srv-world-fail",
                    test_id="t-world-fail",
                    keep_world_changes=True,
                )
            )

        assert result.success is False
        assert result.error_code == "PROMOTE_SWAP_ROLLED_BACK"
        assert result.details["rolled_back"] is True
        assert result.details["restart_attempted"] is True
        assert result.details["restart_ok"] is True

        # Assert all production paths rolled back to original pre-promote state
        assert (srv_dir / "server.properties").read_text(encoding="utf-8") == "motd=ProdOld\n"
        assert (live_mods / "old_mod.jar").read_bytes() == b"old-mod-bytes"
        assert not (live_mods / "new_mod.jar").exists()
        assert (live_world / "level.dat").read_text(encoding="utf-8") == "live-overworld"
        assert (live_nether / "level.dat").read_text(encoding="utf-8") == "live-nether"

        # Assert test directory was completely preserved
        assert (test_mods / "new_mod.jar").read_bytes() == b"new-mod-bytes"
        assert (test_world / "level.dat").read_text(encoding="utf-8") == "test-overworld"
        assert (test_nether / "level.dat").read_text(encoding="utf-8") == "test-nether"
        test_runner.cleanup_test.assert_not_called()

        # Restart was dispatched
        assert any(
            isinstance(call.args[0], StartServerCommand) for call in command_bus.send.call_args_list
        )


@pytest.mark.asyncio
async def test_successful_promote_records_restart_details() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "srv"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("motd=OldServer\n", encoding="utf-8")

        test_dir = srv_dir / ".onx" / "tests" / "t-success"
        test_dir.mkdir(parents=True)
        (test_dir / "server.properties").write_text("motd=PromotedSuccess\n", encoding="utf-8")

        mock_server = MagicMock(spec=Server)
        mock_server.id = ServerId("srv-success")
        mock_server.status = ServerStatus.RUNNING
        mock_server.deployment = ServerDeployment(root_path=str(srv_dir), working_directory=".")

        server_repo = AsyncMock(spec=ServerRepository)
        server_repo.get.return_value = mock_server

        v_repo = InMemoryVersioningRepository()
        manifest = CommitManifest(
            server_type="vanilla",
            minecraft_version="1.21.1",
            configs={"server.properties": "motd=PromotedSuccess\n"},
        )
        commit = ServerCommit(
            id="c-success", server_id="srv-success", message="Success commit", manifest=manifest
        )
        await v_repo.save_commit(commit)

        test_run = ServerTestRun(
            id="t-success",
            server_id="srv-success",
            commit_id="c-success",
            status=TestRunStatus.PASSED,
        )
        await v_repo.save_test_run(test_run)

        command_bus = AsyncMock(spec=CommandBus)
        test_runner = AsyncMock(spec=TestExecutionRunner)

        # 1. Successful promote with successful restart
        command_bus.send.side_effect = [
            CommandResult(
                success=True, data={"status": "stopped", "stop_confirmed": True, "warnings": []}
            ),
            CommandResult(success=True, data={"status": "running"}),
        ]

        handler = PromoteCommitHandler(
            server_repo=server_repo,
            versioning_repo=v_repo,
            command_bus=command_bus,
            test_runner=test_runner,
        )

        result = await handler.handle(
            PromoteCommitCommand(server_id="srv-success", test_id="t-success")
        )

        assert result.success is True
        assert result.details["promoted"] is True
        assert result.details["restart_attempted"] is True
        assert result.details["restart_ok"] is True
        assert result.details["restart_error_code"] is None
        assert result.details["restart_error"] is None
        test_runner.cleanup_test.assert_called_once()

        # 2. Successful promote where restart fails
        command_bus.send.side_effect = [
            CommandResult(
                success=True, data={"status": "stopped", "stop_confirmed": True, "warnings": []}
            ),
            CommandResult(
                success=False, error="Port conflict", error_code="PORT_OCCUPIED"
            ),
        ]

        result2 = await handler.handle(
            PromoteCommitCommand(server_id="srv-success", test_id="t-success")
        )
        assert result2.success is True
        assert result2.details["promoted"] is True
        assert result2.details["restart_attempted"] is True
        assert result2.details["restart_ok"] is False
        assert result2.details["restart_error_code"] == "PORT_OCCUPIED"
        assert result2.details["restart_error"] == "Port conflict"


@pytest.mark.asyncio
async def test_restore_backup_handler_lifecycle_lease_and_active_runtime_guard(
    event_bus: EventBus,
) -> None:
    # 1. Lifecycle lease lock timeout
    mock_lease = MagicMock()

    @asynccontextmanager
    async def timeout_acquire(server_id: str, holder: str = "", wait_timeout: float = 60.0):
        _ = server_id, holder, wait_timeout
        raise ServerLifecycleLockTimeoutError("srv-locked", holder)
        yield

    mock_lease.acquire = timeout_acquire

    # Setup database records for backup
    server_id = "srv-restore-guard"
    backup_id = "bak-restore-guard"
    async with database.session_factory() as session:
        server_repo = SQLServerRepository(session)
        server = Server.create(
            server_id=ServerId(server_id),
            name="Restore Server",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            deployment=ServerDeployment(
                location_type=LocationType.LOCAL,
                root_path=f"/tmp/onx-test/{server_id}",
                working_directory=".",
            ),
        )
        server.start()
        server.mark_running(pid=100, port=25565)
        server.stop(reason="test")
        server.mark_stopped()
        server.collect_events()
        await server_repo.save(server)

        backup_repo = SQLBackupRepository(session)
        job = BackupJob.create(
            backup_id=BackupJobId(backup_id),
            server_id=ServerId(server_id),
        )
        job.mark_completed(size_bytes=100, checksum="abc", storage_path="/tmp/bak.tar.gz")
        await backup_repo.save_job(job)
        await session.commit()

    # Test lock conflict
    handler = RestoreBackupHandler(event_bus, lifecycle_lease=mock_lease)
    res_conflict = await handler.handle(RestoreBackupCommand(backup_id=backup_id))
    assert res_conflict.success is False
    assert res_conflict.error_code == "OPERATION_CONCURRENCY_CONFLICT"

    # 2. Server status is STOPPED, but runtime is active (has external_id or pid)
    async with database.session_factory() as session:
        server_repo = SQLServerRepository(session)
        srv = await server_repo.get(ServerId(server_id))
        srv._runtime = RuntimeInfo(
            status="stopped",
            external_id="onx-active-container",
            pid=9999,
            port=25565,
        )
        await server_repo.save(srv)
        await session.commit()

    # Case A: defer_if_running=False -> returns RESTORE_SERVER_ACTIVE
    handler_no_lease = RestoreBackupHandler(event_bus)
    res_active = await handler_no_lease.handle(
        RestoreBackupCommand(backup_id=backup_id, defer_if_running=False)
    )
    assert res_active.success is False
    assert res_active.error_code == "RESTORE_SERVER_ACTIVE"

    # Case B: defer_if_running=True -> defers restore
    res_deferred = await handler_no_lease.handle(
        RestoreBackupCommand(backup_id=backup_id, defer_if_running=True)
    )
    assert res_deferred.success is True
    assert res_deferred.data["deferred"] is True

    # Case C: Runtime is idle, genuine stopped server -> restores immediately
    async with database.session_factory() as session:
        server_repo = SQLServerRepository(session)
        srv = await server_repo.get(ServerId(server_id))
        srv._runtime = None
        await server_repo.save(srv)
        await session.commit()

    with patch(
        "app.modules.backup.application.commands.restore_backup.perform_safe_restore",
        AsyncMock(return_value=["world", "server.properties"]),
    ), patch(
        "app.modules.backup.application.commands.restore_backup._port_is_listening",
        return_value=False,
    ):
        res_restored = await handler_no_lease.handle(
            RestoreBackupCommand(backup_id=backup_id, defer_if_running=False)
        )
        assert res_restored.success is True
        assert res_restored.data["deferred"] is False
        assert res_restored.data["restored_items"] == ["world", "server.properties"]
