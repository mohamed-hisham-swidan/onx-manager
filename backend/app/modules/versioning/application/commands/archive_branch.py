from __future__ import annotations

import asyncio

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import DomainEvent, EventBus
from app.core.exceptions import BranchProtectedError, BranchRuntimeActiveError, NotFoundError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.application.git_branch_adapter import git_branch_context
from app.modules.versioning.domain.events import BranchArchivedEvent
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.infrastructure.git_repository import MAIN_BRANCH


class ArchiveBranchCommand(Command):
    server_id: str
    name: str


class ArchiveBranchHandler(CommandHandler[ArchiveBranchCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: ArchiveBranchCommand) -> CommandResult:
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
        command: ArchiveBranchCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
        events: list[DomainEvent] | None = None,
    ) -> CommandResult:
        from app.modules.shared.value_objects import ServerId

        try:
            server = await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        branch = await versioning_repo.get_branch_by_name(command.server_id, command.name)
        if branch is None:
            raise NotFoundError(
                f"Branch '{command.name}' not found on server '{command.server_id}'"
            )

        if branch.name == MAIN_BRANCH:
            raise BranchProtectedError("Branch 'main' is protected and cannot be archived")

        if branch.is_protected and not branch.can_archive():
            raise BranchProtectedError(
                f"Cannot archive protected branch '{branch.name}'. "
                "Unprotect the branch before archiving."
            )

        if branch.runtime_status in ("starting", "running"):
            raise BranchRuntimeActiveError(
                f"Cannot archive branch '{branch.name}' while a runtime is active "
                f"(status={branch.runtime_status}); stop the branch runtime first.",
                details={
                    "branch": branch.name,
                    "runtime_status": branch.runtime_status,
                    "active_runtime_id": branch.active_runtime_id,
                },
            )
        active_rt = await versioning_repo.get_active_runtime_for_branch(
            command.server_id, branch.name
        )
        if active_rt is not None:
            raise BranchRuntimeActiveError(
                f"Cannot archive branch '{branch.name}' while a runtime is active.",
                details={
                    "branch": branch.name,
                    "active_runtime_id": active_rt.id,
                    "runtime_status": active_rt.status.value
                    if hasattr(active_rt.status, "value")
                    else str(active_rt.status),
                },
            )
        git_context = git_branch_context(server)
        if git_context is not None:
            git_info = git_context.service.get_branch(
                command.server_id, git_context.server_root, command.name
            )
            if (
                git_info is not None
                and git_info.worktree_locked
                and (git_info.worktree_lock_reason or "").startswith("runtime:")
            ):
                raise BranchRuntimeActiveError(
                    f"Cannot archive branch '{branch.name}' while a runtime is active.",
                    details={
                        "branch": branch.name,
                        "worktree_lock_reason": git_info.worktree_lock_reason,
                    },
                )
            git_context.service.archive_branch(
                command.server_id,
                git_context.server_root,
                command.name,
            )

        branch.archive()
        await versioning_repo.save_branch(branch)

        event = BranchArchivedEvent(
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
            details={
                "branch_id": branch.id,
                "name": branch.name,
                "server_id": command.server_id,
                "status": branch.status.value,
            },
        )
