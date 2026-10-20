from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.command_bus import Command, CommandBus, CommandHandler, CommandResult
from app.core.event_bus import DomainEvent, EventBus
from app.core.exceptions import FilesystemOperationError, NotFoundError, ValidationError
from app.modules.activity.domain.entities import ServerActivityLog
from app.modules.activity.domain.repository import ActivityRepository
from app.modules.backup.application.restore_service import _atomic_replace_dir
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
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        events: list[DomainEvent] = []

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
        was_running = server.status in (ServerStatus.RUNNING, ServerStatus.STARTING)
        if was_running and self._command_bus:
            await self._command_bus.send(StopServerCommand(server_id=command.server_id))

        # 4. Swap manifest configs & mods into production directory
        manifest = commit.manifest
        for rel_path, content in manifest.configs.items():
            tgt_file = Path(server_dir) / rel_path
            try:
                self._fs.write_text_atomic(str(tgt_file), content, encoding="utf-8")
            except OSError as exc:
                raise FilesystemOperationError(str(tgt_file), "write", str(exc)) from exc

        # Swap mods directory if present in test directory
        test_mods = Path(test_dir) / "mods"
        live_mods = Path(server_dir) / "mods"
        if test_mods.is_dir():
            _atomic_replace_dir(str(test_mods), str(live_mods))

        # 5. Atomically swap world changes if requested
        if command.keep_world_changes:
            for w_name in ["world", "world_nether", "world_the_end"]:
                t_world = Path(test_dir) / w_name
                l_world = Path(server_dir) / w_name
                if t_world.is_dir():
                    _atomic_replace_dir(str(t_world), str(l_world))

        # 6. Cleanup test container and directory
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

        # 7. Restart production server if it was previously running
        if was_running and self._command_bus:
            await self._command_bus.send(StartServerCommand(server_id=command.server_id))

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
            },
        )
