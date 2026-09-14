from __future__ import annotations

import uuid

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.entities import ServerBranch
from app.modules.versioning.domain.repository import VersioningRepository


class CreateBranchCommand(Command):
    server_id: str
    name: str
    head_commit_id: str | None = None


class CreateBranchHandler(CommandHandler[CreateBranchCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo

    async def handle(self, command: CreateBranchCommand) -> CommandResult:
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
        command: CreateBranchCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> CommandResult:
        from app.modules.shared.value_objects import ServerId

        # Verify server exists
        try:
            server = await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        # Check existing branch with same name
        existing = await versioning_repo.get_branch_by_name(command.server_id, command.name)
        if existing:
            raise ConflictError(
                f"Branch '{command.name}' already exists on server '{command.server_id}'"
            )

        branch = ServerBranch(
            id=str(uuid.uuid4()),
            server_id=command.server_id,
            name=command.name,
            head_commit_id=command.head_commit_id,
        )
        await versioning_repo.save_branch(branch)

        return CommandResult(
            success=True,
            entity_id=branch.id,
            details={"branch_id": branch.id, "name": branch.name, "server_id": command.server_id},
        )
