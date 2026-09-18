from __future__ import annotations

import asyncio
from typing import Any

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.exceptions import NotFoundError, ValidationError
from app.modules.versioning.domain.entities import BranchProtectionPolicy
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import BranchStatus


class SetBranchProtectionCommand(Command):
    server_id: str
    branch_name: str
    policy: dict[str, Any] | None = None


class SetBranchProtectionHandler(CommandHandler[SetBranchProtectionCommand]):
    def __init__(self, versioning_repo: VersioningRepository | None = None) -> None:
        self._versioning_repo = versioning_repo

    async def handle(self, command: SetBranchProtectionCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._versioning_repo is not None:
            return await self._execute(command, self._versioning_repo)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with database.session_factory() as session:
                    versioning_repo = SQLVersioningRepository(session)
                    res = await self._execute(command, versioning_repo)
                    await session.commit()
                return res
            except Exception as exc:
                is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if is_lock and attempt < max_retries - 1:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                raise
        return CommandResult(success=False, error="Exhausted retries on database lock")

    async def _execute(
        self,
        command: SetBranchProtectionCommand,
        versioning_repo: VersioningRepository,
    ) -> CommandResult:
        branch = await versioning_repo.get_branch_by_name(command.server_id, command.branch_name)
        if branch is None:
            raise NotFoundError(
                f"Branch '{command.branch_name}' not found on server '{command.server_id}'"
            )

        if branch.status == BranchStatus.ARCHIVED:
            raise ValidationError(
                f"Cannot configure protection on archived branch '{branch.name}'"
            )

        policy = (
            BranchProtectionPolicy.from_dict(command.policy)
            if command.policy
            else BranchProtectionPolicy()
        )
        branch.protect(policy)
        await versioning_repo.save_branch(branch)

        return CommandResult(
            success=True,
            entity_id=branch.id,
            details={
                "server_id": command.server_id,
                "branch_name": branch.name,
                "is_protected": branch.is_protected,
                "policy": branch.protection_policy.to_dict() if branch.protection_policy else None,
            },
        )


class RemoveBranchProtectionCommand(Command):
    server_id: str
    branch_name: str


class RemoveBranchProtectionHandler(CommandHandler[RemoveBranchProtectionCommand]):
    def __init__(self, versioning_repo: VersioningRepository | None = None) -> None:
        self._versioning_repo = versioning_repo

    async def handle(self, command: RemoveBranchProtectionCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._versioning_repo is not None:
            return await self._execute(command, self._versioning_repo)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with database.session_factory() as session:
                    versioning_repo = SQLVersioningRepository(session)
                    res = await self._execute(command, versioning_repo)
                    await session.commit()
                return res
            except Exception as exc:
                is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if is_lock and attempt < max_retries - 1:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                raise
        return CommandResult(success=False, error="Exhausted retries on database lock")

    async def _execute(
        self,
        command: RemoveBranchProtectionCommand,
        versioning_repo: VersioningRepository,
    ) -> CommandResult:
        branch = await versioning_repo.get_branch_by_name(command.server_id, command.branch_name)
        if branch is None:
            raise NotFoundError(
                f"Branch '{command.branch_name}' not found on server '{command.server_id}'"
            )

        if branch.status == BranchStatus.ARCHIVED:
            raise ValidationError(
                f"Cannot unprotect archived branch '{branch.name}'"
            )

        branch.unprotect()
        await versioning_repo.save_branch(branch)

        return CommandResult(
            success=True,
            entity_id=branch.id,
            details={
                "server_id": command.server_id,
                "branch_name": branch.name,
                "is_protected": branch.is_protected,
                "policy": None,
            },
        )
