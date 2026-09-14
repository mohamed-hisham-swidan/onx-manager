from __future__ import annotations

from pathlib import Path

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.exceptions import NotFoundError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
    TestExecutionRunner,
    TestHandle,
)


class DiscardTestCommand(Command):
    server_id: str
    test_id: str


class DiscardTestHandler(CommandHandler[DiscardTestCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        test_runner: TestExecutionRunner | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._test_runner = test_runner or DockerTestExecutionRunner()

    async def handle(self, command: DiscardTestCommand) -> CommandResult:
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
        command: DiscardTestCommand,
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

        server_dir = server.deployment.server_dir
        test_dir = str((Path(server_dir) / ".onx" / "tests" / command.test_id).resolve())

        # 2. Cleanup test container and directory
        handle = TestHandle(
            test_id=command.test_id,
            server_id=command.server_id,
            container_name=f"onx-test-{command.test_id}",
            test_dir=test_dir,
            sidecar_runner=None,
            status=test_run.status,
        )
        await self._test_runner.cleanup_test(handle)

        # 3. Mark test run as cancelled
        test_run.mark_cancelled("Discarded by user")
        await versioning_repo.save_test_run(test_run)

        return CommandResult(
            success=True,
            entity_id=command.test_id,
            details={
                "server_id": command.server_id,
                "test_id": command.test_id,
                "status": "CANCELLED",
                "discarded": True,
            },
        )
