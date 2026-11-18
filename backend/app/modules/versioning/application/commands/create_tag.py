from __future__ import annotations

import asyncio
import uuid

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import DomainEvent, EventBus
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.entities import Tag
from app.modules.versioning.domain.events import TagCreatedEvent
from app.modules.versioning.domain.repository import VersioningRepository


class CreateTagCommand(Command):
    server_id: str
    name: str
    commit_id: str


class CreateTagHandler(CommandHandler[CreateTagCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: CreateTagCommand) -> CommandResult:
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
        command: CreateTagCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
        events: list[DomainEvent] | None = None,
    ) -> CommandResult:
        from app.modules.shared.value_objects import ServerId
        from app.modules.versioning.application.git_branch_adapter import git_branch_context

        # Verify server exists
        try:
            server = await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc
        if server is None:
            raise NotFoundError(f"Server '{command.server_id}' not found")

        git_context = git_branch_context(server)
        if git_context is not None:
            return await self._execute_native_git(
                command, server, git_context, versioning_repo, events
            )

        # Verify commit exists and belongs to server
        commit = await versioning_repo.get_commit(command.commit_id)
        if commit is None or commit.server_id != command.server_id:
            raise NotFoundError(
                f"Commit '{command.commit_id}' not found on server '{command.server_id}'"
            )

        # Check existing tag with same name
        existing = await versioning_repo.get_tag(command.server_id, command.name)
        if existing is not None:
            raise ConflictError(
                f"Tag '{command.name}' already exists on server '{command.server_id}'"
            )

        tag = Tag(
            id=str(uuid.uuid4()),
            server_id=command.server_id,
            name=command.name,
            commit_id=command.commit_id,
        )
        await versioning_repo.save_tag(tag)

        event = TagCreatedEvent(
            server_id=command.server_id,
            tag_name=tag.name,
            commit_id=tag.commit_id,
        )
        if events is not None:
            events.append(event)
        elif self._event_bus is not None:
            await self._event_bus.publish(event)

        return CommandResult(
            success=True,
            entity_id=tag.id,
            details={
                "tag_id": tag.id,
                "name": tag.name,
                "server_id": tag.server_id,
                "commit_id": tag.commit_id,
            },
        )

    async def _execute_native_git(self, command, server, git_context, versioning_repo, events=None):
        import uuid as _uuid

        from app.core.exceptions import ValidationError
        from app.modules.versioning.domain.entities import ServerCommit
        from app.modules.versioning.domain.value_objects import CommitManifest

        # validate tag name
        runner = git_context.service.open_runner(str(server.id), git_context.server_root)
        check = runner.run("check-ref-format", f"refs/tags/{command.name}", check=False)
        if check.returncode != 0:
            raise ValidationError(f"Invalid tag name '{command.name}'")

        # duplicate in repo
        existing_ref = runner.run(
            "rev-parse", "--verify", "--quiet", f"refs/tags/{command.name}", check=False
        )
        if existing_ref.returncode == 0:
            raise ConflictError(f"Tag '{command.name}' already exists")

        # duplicate in db
        db_existing = await versioning_repo.get_tag(command.server_id, command.name)
        if db_existing is not None:
            raise ConflictError(
                f"Tag '{command.name}' already exists on server '{command.server_id}'"
            )

        # resolve commit
        resolved = runner.run(
            "rev-parse", "--verify", "--quiet", f"{command.commit_id}^{{commit}}", check=False
        )
        resolved_sha = None
        if resolved.returncode == 0:
            resolved_sha = resolved.stdout.strip()
        else:
            db_commit = await versioning_repo.get_commit(command.commit_id)
            if db_commit is not None and db_commit.server_id == command.server_id:
                resolved_sha = command.commit_id
                # ensure in repo
                check2 = runner.run(
                    "rev-parse", "--verify", "--quiet", f"{resolved_sha}^{{commit}}", check=False
                )
                if check2.returncode != 0:
                    raise NotFoundError(f"Commit '{command.commit_id}' not found in repository")
        if not resolved_sha:
            raise NotFoundError(
                f"Commit '{command.commit_id}' not found on server '{command.server_id}'"
            )

        # create tag
        runner.run("tag", command.name, resolved_sha)

        # project commit if missing
        if await versioning_repo.get_commit(resolved_sha) is None:
            commit = ServerCommit(
                id=resolved_sha,
                server_id=command.server_id,
                message="",
                manifest=CommitManifest(
                    server_type=str(server.server_type),
                    minecraft_version=str(server.minecraft_version),
                ),
                author_id=None,
            )
            await versioning_repo.save_commit(commit)

        tag = Tag(
            id=str(_uuid.uuid4()),
            server_id=command.server_id,
            name=command.name,
            commit_id=resolved_sha,
        )
        await versioning_repo.save_tag(tag)

        event = TagCreatedEvent(
            server_id=command.server_id, tag_name=tag.name, commit_id=tag.commit_id
        )
        if events is not None:
            events.append(event)
        elif self._event_bus is not None:
            await self._event_bus.publish(event)

        return CommandResult(
            success=True,
            entity_id=tag.id,
            details={
                "tag_id": tag.id,
                "name": tag.name,
                "server_id": tag.server_id,
                "commit_id": tag.commit_id,
            },
        )
