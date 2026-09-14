from __future__ import annotations

import uuid

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import NotFoundError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.entities import ServerTestRun
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import TestRunStatus
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

        if self._server_repo is not None and self._versioning_repo is not None:
            return await self._execute(command, self._server_repo, self._versioning_repo)

        async with database.session_factory() as session:
            server_repo = self._server_repo or SQLServerRepository(session)
            versioning_repo = self._versioning_repo or SQLVersioningRepository(session)
            res = await self._execute(command, server_repo, versioning_repo)
            await session.commit()
            return res

    async def _execute(
        self,
        command: RunIsolatedTestCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
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
        server_bot_settings = getattr(server, "bot_verification_settings", None)
        run_overrides = {
            "bot_count": command.bot_count,
            "duration_minutes": command.duration_minutes,
            "placement_mode": command.placement_mode,
            "bot_tech": command.bot_tech,
        }
        bot_cfg = BotConfigResolver.resolve_config(
            server_type=server.server_type,
            server_bot_settings=server_bot_settings,
            run_overrides=run_overrides,
        )

        # 4. Prepare and record test run in database
        test_id = str(uuid.uuid4())
        test_run = ServerTestRun(
            id=test_id,
            server_id=command.server_id,
            commit_id=target_commit_id,
            node_id="local",
            status=TestRunStatus.RUNNING,
            bot_count=bot_cfg.bot_count,
            duration_minutes=bot_cfg.duration_minutes,
            placement_mode=bot_cfg.placement_mode,
            bot_tech=bot_cfg.bot_tech,
        )
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

        handle = await self._test_runner.run_test(spec)

        if self._event_bus is not None:
            from app.modules.versioning.domain.events import TestRunStartedEvent

            await self._event_bus.publish(
                TestRunStartedEvent(
                    server_id=command.server_id,
                    test_id=test_id,
                    commit_id=target_commit_id,
                    bot_count=bot_cfg.bot_count,
                    duration_minutes=bot_cfg.duration_minutes,
                )
            )

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
            },
        )
