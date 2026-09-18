from __future__ import annotations

import asyncio

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import DomainEvent, EventBus
from app.core.exceptions import NotFoundError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.application.scheduling.admission import admit
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.infrastructure.config_resolver import BotConfigResolver
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
    TestExecutionRunner,
    TestSpec,
)


class RunIsolatedTestCommand(Command):
    server_id: str
    commit_id: str | None = None
    bot_count: int | None = None
    duration_minutes: int | None = None
    placement_mode: str | None = None
    bot_tech: str | None = None
    test_definition_id: str | None = None


class RunIsolatedTestHandler(CommandHandler[RunIsolatedTestCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        test_runner: TestExecutionRunner | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._test_runner = test_runner or DockerTestExecutionRunner()
        self._event_bus = event_bus

    async def handle(self, command: RunIsolatedTestCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        events: list[DomainEvent] = []

        if self._server_repo is not None and self._versioning_repo is not None:
            res = await self._execute(command, self._server_repo, self._versioning_repo, events)
        else:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with database.session_factory() as session:
                        server_repo = self._server_repo or SQLServerRepository(session)
                        versioning_repo = self._versioning_repo or SQLVersioningRepository(session)
                        events.clear()
                        res = await self._execute(command, server_repo, versioning_repo, events)
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
        command: RunIsolatedTestCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
        events: list[DomainEvent] | None = None,
    ) -> CommandResult:
        from app.modules.shared.value_objects import ServerId

        # 1. Fetch server
        try:
            server = await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        # 2. Resolve commit
        target_commit_id = command.commit_id
        if not target_commit_id:
            commits = await versioning_repo.list_commits(command.server_id, limit=1)
            if not commits:
                raise NotFoundError(
                    f"No commits found for server '{command.server_id}'. Create a commit first."
                )
            commit = commits[0]
            target_commit_id = commit.id
        else:
            commit = await versioning_repo.get_commit(target_commit_id)
            if commit is None or commit.server_id != command.server_id:
                raise NotFoundError(
                    f"Commit '{target_commit_id}' not found for server '{command.server_id}'"
                )

        # 3. Resolve layered bot configuration (§3.5.6)
        bot_count = command.bot_count
        duration_minutes = command.duration_minutes
        placement_mode = command.placement_mode
        bot_tech = command.bot_tech

        if command.test_definition_id:
            test_def = await versioning_repo.get_test_definition(command.test_definition_id)
            if test_def is None or test_def.server_id != command.server_id:
                raise NotFoundError(
                    f"TestDefinition '{command.test_definition_id}' not found "
                    f"for server '{command.server_id}'"
                )
            if bot_count is None:
                bot_count = test_def.bot_count
            if duration_minutes is None:
                duration_minutes = max(1, test_def.duration_seconds // 60)
            if placement_mode is None:
                placement_mode = (
                    test_def.placement_mode.value
                    if hasattr(test_def.placement_mode, "value")
                    else str(test_def.placement_mode)
                )
            if bot_tech is None:
                bot_tech = (
                    test_def.bot_technology.value
                    if hasattr(test_def.bot_technology, "value")
                    else str(test_def.bot_technology)
                )

        server_bot_settings = getattr(server, "bot_verification_settings", None)
        run_overrides = {
            "bot_count": bot_count,
            "duration_minutes": duration_minutes,
            "placement_mode": placement_mode,
            "bot_tech": bot_tech,
        }
        bot_cfg = BotConfigResolver.resolve_config(
            server_type=server.server_type,
            server_bot_settings=server_bot_settings,
            run_overrides=run_overrides,
        )

        # 4. Global admission gate (Stage D). admit() runs reap-read-check-earmark
        # inside one DB-serialized transaction and owns the PENDING-row insert
        # (with RAM/core earmarks); the container starts only after it commits.
        # Raises ConflictError (409, cap) or BotRunInsufficientResourcesError (422).
        reservation = await admit(
            server_id=command.server_id,
            commit_id=target_commit_id,
            bot_count=bot_cfg.bot_count,
            server_type=server.server_type,
            duration_minutes=bot_cfg.duration_minutes,
            placement_mode=bot_cfg.placement_mode.value,
            bot_tech=bot_cfg.bot_tech.value,
        )
        test_run = reservation.test_run
        test_id = test_run.id
        test_run.test_definition_id = command.test_definition_id
        test_run.mark_running()
        await versioning_repo.save_test_run(test_run)

        # 5. Launch test runner pipeline
        spec = TestSpec(
            test_id=test_id,
            server_id=command.server_id,
            commit=commit,
            server_dir=server.deployment.server_dir,
            bot_config=bot_cfg,
            minecraft_version=server.minecraft_version,
        )

        try:
            await self._test_runner.run_test(spec)
        except Exception as exc:
            # Release the earmark by explicit terminal transition (stale-reaping
            # would also catch it, but an explicit FAILED carries the cause).
            test_run.mark_failed(f"Runner failed before verification: {exc}")
            await versioning_repo.save_test_run(test_run)
            raise

        from app.modules.versioning.domain.events import TestRunStartedEvent

        event = TestRunStartedEvent(
            server_id=command.server_id,
            test_id=test_id,
            commit_id=target_commit_id,
            bot_count=bot_cfg.bot_count,
            duration_minutes=bot_cfg.duration_minutes,
        )
        if events is not None:
            events.append(event)
        elif self._event_bus is not None:
            await self._event_bus.publish(event)

        return CommandResult(
            success=True,
            entity_id=test_id,
            details={
                "test_id": test_id,
                "server_id": command.server_id,
                "commit_id": target_commit_id,
                "status": "RUNNING",
                "bot_count": bot_cfg.bot_count,
                "duration_minutes": bot_cfg.duration_minutes,
                "bot_tech": bot_cfg.bot_tech.value,
                "placement_mode": bot_cfg.placement_mode.value,
                "test_definition_id": command.test_definition_id,
            },
        )
