from __future__ import annotations

import asyncio
import logging
import os
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path

from app.core.command_bus import Command, CommandBus, CommandHandler, CommandResult
from app.core.event_bus import DomainEvent, EventBus
from app.core.exceptions import (
    FilesystemOperationError,
    NotFoundError,
    ValidationError,
)
from app.core.fs_utils import assert_inside_root
from app.modules.activity.domain.entities import ServerActivityLog
from app.modules.activity.domain.repository import ActivityRepository
from app.modules.server.application.commands.start_server import StartServerCommand
from app.modules.server.application.commands.stop_server import StopServerCommand
from app.modules.server.domain.aggregate import ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.fs import FileSystem, local_fs
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import TestRunStatus
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
    TestExecutionRunner,
    TestHandle,
)

logger = logging.getLogger(__name__)


def _is_stop_confirmed(result: CommandResult | None) -> bool:
    """Return True iff StopServerCommand confirmed runtime & port stop without warnings."""
    if result is None or not getattr(result, "success", False):
        return False
    data = getattr(result, "data", None)
    if not isinstance(data, dict) or not data:
        return False
    if data.get("stop_confirmed") is False:
        return False
    if data.get("warnings") or data.get("provider_errors"):
        return False
    if "stop_confirmed" in data:
        return data.get("stop_confirmed") is True
    return data.get("status") == "stopped"


class PromoteCommitCommand(Command):
    server_id: str
    test_id: str
    keep_world_changes: bool = False
    force: bool = False
    force_reason: str | None = None
    actor_id: str | None = None


class PromoteCommitHandler(CommandHandler[PromoteCommitCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        command_bus: CommandBus | None = None,
        test_runner: TestExecutionRunner | None = None,
        event_bus: EventBus | None = None,
        activity_repo: ActivityRepository | None = None,
        fs: FileSystem | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._command_bus = command_bus
        self._test_runner = test_runner or DockerTestExecutionRunner()
        self._event_bus = event_bus
        self._activity_repo = activity_repo
        self._fs = fs or local_fs

    async def handle(self, command: PromoteCommitCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.activity.infrastructure.repository import SQLActivityRepository
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.application.mode_guard import ensure_versioning_allowed
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        events: list[DomainEvent] = []

        if self._server_repo is not None:
            await ensure_versioning_allowed(command.server_id, server_repo=self._server_repo)

        if self._server_repo is not None and self._versioning_repo is not None:
            activity_repo = self._activity_repo or SQLActivityRepository()
            res = await self._execute(
                command, self._server_repo, self._versioning_repo, activity_repo, events
            )
        else:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with database.session_factory() as session:
                        await ensure_versioning_allowed(command.server_id, session=session)
                        server_repo = self._server_repo or SQLServerRepository(session)
                        versioning_repo = self._versioning_repo or SQLVersioningRepository(session)
                        activity_repo = self._activity_repo or SQLActivityRepository(session)
                        events.clear()
                        res = await self._execute(
                            command, server_repo, versioning_repo, activity_repo, events
                        )
                        await session.commit()
                    break
                except Exception as exc:
                    is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                    if is_lock and attempt < max_retries - 1:
                        await asyncio.sleep(0.05 * (2**attempt))
                        continue
                    raise

        if self._event_bus is not None and res.success:
            for ev in events:
                await self._event_bus.publish(ev)

        return res

    async def _execute(
        self,
        command: PromoteCommitCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
        activity_repo: ActivityRepository,
        events: list[DomainEvent] | None = None,
    ) -> CommandResult:
        from app.modules.shared.value_objects import ServerId

        # 1. Fetch server & test run
        try:
            server = await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        test_run = await versioning_repo.get_test_run(command.test_id)
        if test_run is None or test_run.server_id != command.server_id:
            raise NotFoundError(
                f"Test run '{command.test_id}' not found for server '{command.server_id}'"
            )

        commit = await versioning_repo.get_commit(test_run.commit_id)
        if commit is None:
            raise NotFoundError(f"Commit '{test_run.commit_id}' not found")

        # 2. Safety Gating: Verify isolated test status (§3.3)
        if not command.force:
            if test_run.status != TestRunStatus.PASSED:
                status_str = (
                    test_run.status.value
                    if hasattr(test_run.status, "value")
                    else str(test_run.status)
                )
                raise ValidationError(
                    f"Cannot promote commit '{test_run.commit_id}': Test run '{test_run.id}' "
                    f"has status '{status_str}'. "
                    "Only PASSED test runs can be promoted to production."
                )

            # Invalidation guard: Ensure no subsequent test run for this commit failed
            all_runs = await versioning_repo.list_test_runs(command.server_id, limit=50)
            newer_failures = [
                r
                for r in all_runs
                if r.commit_id == test_run.commit_id
                and r.created_at > test_run.created_at
                and r.status == TestRunStatus.FAILED
            ]
            if newer_failures:
                raise ValidationError(
                    f"Cannot promote commit '{test_run.commit_id}': A subsequent test run "
                    f"('{newer_failures[0].id}') failed for this commit. "
                    "Re-verify the commit before promoting."
                )

        # Audit mandatory activity log on force bypass
        if command.force:
            summary = (
                f"Commit '{commit.id[:8]}' was force-promoted to production "
                "bypassing test verification"
            )
            activity_log = ServerActivityLog(
                server_id=command.server_id,
                event_type="versioning.force_promoted",
                summary=summary,
                actor_type="user" if command.actor_id else "system",
                actor_id=command.actor_id,
                details={
                    "commit_id": commit.id,
                    "test_id": command.test_id,
                    "test_status": (
                        test_run.status.value
                        if hasattr(test_run.status, "value")
                        else str(test_run.status)
                    ),
                    "forced": True,
                    "force_reason": command.force_reason or "No reason provided",
                },
            )
            await activity_repo.save(activity_log)

        from app.modules.versioning.domain.paths import resolve_test_dir

        server_dir = server.deployment.server_dir
        test_dir = str(resolve_test_dir(server_dir, command.test_id))

        # 3. Stop production server if running
        was_active = server.status in (
            ServerStatus.RUNNING,
            ServerStatus.STARTING,
            ServerStatus.STOPPING,
        )
        was_running = server.status in (ServerStatus.RUNNING, ServerStatus.STARTING)
        if was_active:
            stop_result: CommandResult | None = None
            if self._command_bus:
                try:
                    stop_result = await self._command_bus.send(
                        StopServerCommand(server_id=str(server.id))
                    )
                except Exception as exc:
                    logger.warning("StopServerCommand raised exception during promote: %s", exc)
                    stop_result = CommandResult(
                        success=False,
                        error=str(exc),
                        error_code="STOP_FAILED",
                        data={"error": str(exc)},
                    )

            if not _is_stop_confirmed(stop_result):
                return CommandResult(
                    success=False,
                    error="Cannot promote: production server could not be confirmed stopped",
                    error_code="PROMOTE_STOP_NOT_CONFIRMED",
                    details={"stop_result": stop_result.data if stop_result else None},
                )

        # 4. Swap manifest configs, mods, and worlds with all-or-nothing rollback journal (§3.5)
        server_path = Path(server_dir)
        test_path = Path(test_dir)
        tx_root = server_path.parent / f".onx-promote-tx-{server.id}-{uuid.uuid4().hex[:8]}"
        staged_root = tx_root / "staged"
        backup_root = tx_root / "backup"
        staged_root.mkdir(parents=True, exist_ok=True)
        backup_root.mkdir(parents=True, exist_ok=True)

        applied_journal: list[Callable[[], None]] = []
        rollback_ok = True
        restart_attempted = False
        restart_ok = False
        restart_error_code: str | None = None
        restart_error: str | None = None

        try:
            # 4.1 Stage & apply configs
            manifest = commit.manifest
            if manifest and manifest.configs:
                raw_configs = manifest.configs
                if isinstance(raw_configs, dict):
                    config_items = list(raw_configs.items())
                elif isinstance(raw_configs, list):
                    config_items = []
                    for item in raw_configs:
                        if hasattr(item, "path"):
                            config_items.append((item.path, getattr(item, "content", "")))
                        elif isinstance(item, dict):
                            config_items.append((item.get("path", ""), item.get("content", "")))
                else:
                    config_items = []

                # Pre-validate and stage into tx_root / staged / configs
                staged_configs: list[tuple[Path, str, str]] = []
                for rel_path, content in config_items:
                    target_file = assert_inside_root(server_path / rel_path, server_path)
                    staged_file = staged_root / "configs" / rel_path
                    staged_file.parent.mkdir(parents=True, exist_ok=True)
                    staged_file.write_text(content, encoding="utf-8")
                    staged_configs.append((target_file, rel_path, content))

                # Apply configs with backup & rollback closures
                for target_file, rel_path, content in staged_configs:
                    backup_file = backup_root / "configs" / rel_path
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    had_file = target_file.exists()
                    if had_file:
                        shutil.copy2(target_file, backup_file)
                        applied_journal.append(
                            lambda tf=target_file, bf=backup_file: os.replace(bf, tf)
                        )
                    else:
                        applied_journal.append(
                            lambda tf=target_file: tf.unlink() if tf.exists() else None
                        )

                    try:
                        self._fs.write_text_atomic(str(target_file), content, encoding="utf-8")
                    except OSError as exc:
                        raise FilesystemOperationError(str(target_file), "write", str(exc)) from exc

            # 4.2 Stage & swap mods
            test_mods = test_path / "mods"
            if test_mods.is_dir():
                staged_mods = staged_root / "mods"
                shutil.copytree(test_mods, staged_mods, symlinks=True)
                prod_mods = server_path / "mods"
                backup_mods = backup_root / "mods"
                had_mods = prod_mods.exists()
                if had_mods:
                    os.replace(prod_mods, backup_mods)

                    def _restore_pre_swap_mods(bm=backup_mods, pm=prod_mods):
                        if bm.exists():
                            os.replace(bm, pm)

                    applied_journal.append(_restore_pre_swap_mods)

                os.replace(staged_mods, prod_mods)
                if had_mods:
                    applied_journal.pop()

                def _rollback_mods(pm=prod_mods, bm=backup_mods, had_bak=had_mods):
                    if pm.exists():
                        if pm.is_dir() and not pm.is_symlink():
                            shutil.rmtree(pm, ignore_errors=True)
                        else:
                            pm.unlink(missing_ok=True)
                    if had_bak and bm.exists():
                        os.replace(bm, pm)

                applied_journal.append(_rollback_mods)

            # 4.3 Stage & swap world* directories if keep_world_changes
            if command.keep_world_changes and test_path.is_dir():
                for world_dir in sorted(test_path.glob("world*")):
                    if not world_dir.is_dir():
                        continue
                    w_name = world_dir.name
                    staged_world = staged_root / "worlds" / w_name
                    staged_world.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(world_dir, staged_world, symlinks=True)

                    prod_world = server_path / w_name
                    backup_world = backup_root / "worlds" / w_name
                    backup_world.parent.mkdir(parents=True, exist_ok=True)

                    had_world = prod_world.exists()
                    if had_world:
                        os.replace(prod_world, backup_world)

                        def _restore_pre_swap_world(bw=backup_world, pw=prod_world):
                            if bw.exists():
                                os.replace(bw, pw)

                        applied_journal.append(_restore_pre_swap_world)

                    os.replace(staged_world, prod_world)
                    if had_world:
                        applied_journal.pop()

                    def _rollback_world(pw=prod_world, bw=backup_world, had_bak=had_world):
                        if pw.exists():
                            if pw.is_dir() and not pw.is_symlink():
                                shutil.rmtree(pw, ignore_errors=True)
                            else:
                                pw.unlink(missing_ok=True)
                        if had_bak and bw.exists():
                            os.replace(bw, pw)

                    applied_journal.append(_rollback_world)

        except Exception as exc:
            logger.error("Promote failed during swap: %s. Initiating rollback...", exc)
            rollback_ok = True
            for rollback_fn in reversed(applied_journal):
                try:
                    rollback_fn()
                except Exception as rb_err:
                    logger.critical("Error during rollback action: %s", rb_err)
                    rollback_ok = False

            if rollback_ok:
                shutil.rmtree(tx_root, ignore_errors=True)
            else:
                logger.critical("Rollback failed; transaction backup preserved at %s", backup_root)

            # Do not clean up test_server
            restart_attempted = was_running
            restart_ok = False
            if was_running and rollback_ok and self._command_bus:
                try:
                    restart_res = await self._command_bus.send(
                        StartServerCommand(server_id=str(server.id))
                    )
                    restart_ok = bool(restart_res and restart_res.success)
                except Exception as start_err:
                    logger.error("Failed to restart server after promote rollback: %s", start_err)
                    restart_ok = False

            return CommandResult(
                success=False,
                error=f"Promote failed and was rolled back: {exc}",
                error_code="PROMOTE_SWAP_ROLLED_BACK",
                details={
                    "rolled_back": rollback_ok,
                    "restart_attempted": restart_attempted,
                    "restart_ok": restart_ok,
                },
            )

        # On success of all swaps:
        shutil.rmtree(tx_root, ignore_errors=True)

        # 5. Cleanup test container and directory
        handle = TestHandle(
            test_id=command.test_id,
            server_id=command.server_id,
            container_name=f"onx-test-{command.test_id}",
            test_dir=test_dir,
            server_dir=server_dir,
            sidecar_runner=None,
            status=test_run.status,
            operation_id=test_run.operation_id,
        )
        await self._test_runner.cleanup_test(handle, passed=True, server_dir=server_dir)

        # 6. Restart production server if it was previously running
        if was_running:
            restart_attempted = True
            start_res: CommandResult | None = None
            if self._command_bus:
                try:
                    start_res = await self._command_bus.send(
                        StartServerCommand(server_id=str(server.id))
                    )
                except Exception as exc:
                    logger.error("Failed to restart server after promote: %s", exc)
                    start_res = CommandResult(
                        success=False, error=str(exc), error_code="START_FAILED"
                    )

            restart_ok = bool(start_res and start_res.success)
            restart_error_code = (
                start_res.error_code if start_res and not start_res.success else None
            )
            restart_error = (
                start_res.error if start_res and not start_res.success else None
            )

        from app.modules.versioning.domain.events import CommitPromotedEvent

        event = CommitPromotedEvent(
            server_id=command.server_id,
            commit_id=commit.id,
            test_id=command.test_id,
            keep_world_changes=command.keep_world_changes,
            forced=command.force,
            actor_id=command.actor_id,
        )
        if events is not None:
            events.append(event)
        elif self._event_bus is not None:
            await self._event_bus.publish(event)

        return CommandResult(
            success=True,
            entity_id=commit.id,
            details={
                "server_id": command.server_id,
                "commit_id": commit.id,
                "test_id": command.test_id,
                "kept_world_changes": command.keep_world_changes,
                "forced": command.force,
                "force_reason": command.force_reason,
                "promoted": True,
                "restart_attempted": restart_attempted,
                "restart_ok": restart_ok,
                "restart_error_code": restart_error_code,
                "restart_error": restart_error,
            },
        )
