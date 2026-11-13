from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import DomainEvent, EventBus
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.application.git_branch_adapter import git_branch_context
from app.modules.versioning.domain.entities import ServerBranch
from app.modules.versioning.domain.events import BranchCreatedEvent
from app.modules.versioning.domain.repository import VersioningRepository

MAX_DB_BRANCH_NAME_LENGTH = 64


class CreateBranchCommand(Command):
    server_id: str
    name: str
    head_commit_id: str | None = None


class CreateBranchHandler(CommandHandler[CreateBranchCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: CreateBranchCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.application.mode_guard import ensure_versioning_allowed
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        events: list[DomainEvent] = []

        if self._server_repo is not None:
            await ensure_versioning_allowed(command.server_id, server_repo=self._server_repo)

        if self._server_repo is not None and self._versioning_repo is not None:
            res = await self._execute(command, self._server_repo, self._versioning_repo, events)
        else:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with database.session_factory() as session:
                        await ensure_versioning_allowed(command.server_id, session=session)
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
        command: CreateBranchCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
        events: list[DomainEvent] | None = None,
    ) -> CommandResult:
        from app.modules.shared.value_objects import ServerId

        # Verify server exists
        try:
            server = await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        if len(command.name) > MAX_DB_BRANCH_NAME_LENGTH:
            raise ValidationError(
                f"Branch name must be at most {MAX_DB_BRANCH_NAME_LENGTH} characters",
                field="name",
            )

        # Check existing branch with same name
        existing = await versioning_repo.get_branch_by_name(command.server_id, command.name)
        if existing:
            raise ConflictError(
                f"Branch '{command.name}' already exists on server '{command.server_id}'"
            )

        if command.head_commit_id:
            head_commit = await versioning_repo.get_commit(command.head_commit_id)
            if head_commit is None or head_commit.server_id != command.server_id:
                raise NotFoundError(
                    f"Head commit '{command.head_commit_id}' not found on "
                    f"server '{command.server_id}'"
                )

        from app.modules.versioning.domain.value_objects import BranchStatus

        git_context = git_branch_context(server)
        if git_context is not None:
            if command.head_commit_id:
                raise ValidationError(
                    "head_commit_id is not supported for Git-backed branches; "
                    "branches start from main",
                    field="head_commit_id",
                )
            git_context.service.create_branch(
                command.server_id,
                git_context.server_root,
                command.name,
            )
            branch = ServerBranch(
                id=str(uuid.uuid4()),
                server_id=command.server_id,
                name=command.name,
                head_commit_id=None,
                status=BranchStatus.ACTIVE,
            )
            try:
                await versioning_repo.save_branch(branch)
            except Exception:
                with suppress(Exception):
                    git_context.service.delete_branch(
                        command.server_id,
                        git_context.server_root,
                        command.name,
                    )
                raise
        else:
            branch = ServerBranch(
                id=str(uuid.uuid4()),
                server_id=command.server_id,
                name=command.name,
                head_commit_id=command.head_commit_id,
                status=BranchStatus.ACTIVE if command.head_commit_id else BranchStatus.CREATED,
            )
            await versioning_repo.save_branch(branch)

        event = BranchCreatedEvent(
            server_id=command.server_id,
            branch_name=branch.name,
            branch_id=branch.id,
        )
        if events is not None:
            events.append(event)
        elif self._event_bus is not None:
            await self._event_bus.publish(event)

        return CommandResult(
            success=True,
            entity_id=branch.id,
            details={"branch_id": branch.id, "name": branch.name, "server_id": command.server_id},
        )
