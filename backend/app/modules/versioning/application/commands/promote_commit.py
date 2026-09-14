from __future__ import annotations

from pathlib import Path

from app.core.command_bus import Command, CommandBus, CommandHandler, CommandResult
from app.core.exceptions import NotFoundError
from app.modules.backup.application.restore_service import _atomic_replace_dir
from app.modules.server.application.commands.start_server import StartServerCommand
from app.modules.server.application.commands.stop_server import StopServerCommand
from app.modules.server.domain.aggregate import ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
    TestExecutionRunner,
    TestHandle,
)


class PromoteCommitCommand(Command):
    server_id: str
    test_id: str
    keep_world_changes: bool = False


class PromoteCommitHandler(CommandHandler[PromoteCommitCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        command_bus: CommandBus | None = None,
        test_runner: TestExecutionRunner | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._command_bus = command_bus
        self._test_runner = test_runner or DockerTestExecutionRunner()

    async def handle(self, command: PromoteCommitCommand) -> CommandResult:
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
        command: PromoteCommitCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
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

        server_dir = server.deployment.server_dir
        test_dir = str((Path(server_dir) / ".onx" / "tests" / command.test_id).resolve())

        # 2. Stop production server if running
        was_running = server.status in (ServerStatus.RUNNING, ServerStatus.STARTING)
        if was_running and self._command_bus:
            await self._command_bus.send(StopServerCommand(server_id=command.server_id))

        # 3. Swap manifest configs & mods into production directory
        manifest = commit.manifest
        for rel_path, content in manifest.configs.items():
            tgt_file = Path(server_dir) / rel_path
            tgt_file.parent.mkdir(parents=True, exist_ok=True)
            tgt_file.write_text(content, encoding="utf-8")

        # Swap mods directory if present in test directory
        test_mods = Path(test_dir) / "mods"
        live_mods = Path(server_dir) / "mods"
        if test_mods.is_dir():
            _atomic_replace_dir(str(test_mods), str(live_mods))

        # 4. Atomically swap world changes if requested
        if command.keep_world_changes:
            for w_name in ["world", "world_nether", "world_the_end"]:
                t_world = Path(test_dir) / w_name
                l_world = Path(server_dir) / w_name
                if t_world.is_dir():
                    _atomic_replace_dir(str(t_world), str(l_world))

        # 5. Cleanup test container and directory
        handle = TestHandle(
            test_id=command.test_id,
            server_id=command.server_id,
            container_name=f"onx-test-{command.test_id}",
            test_dir=test_dir,
            sidecar_runner=None,
            status=test_run.status,
        )
        await self._test_runner.cleanup_test(handle)

        # 6. Restart production server if it was previously running
        if was_running and self._command_bus:
            await self._command_bus.send(StartServerCommand(server_id=command.server_id))

        return CommandResult(
            success=True,
            entity_id=commit.id,
            details={
                "server_id": command.server_id,
                "commit_id": commit.id,
                "test_id": command.test_id,
                "kept_world_changes": command.keep_world_changes,
                "promoted": True,
            },
        )
