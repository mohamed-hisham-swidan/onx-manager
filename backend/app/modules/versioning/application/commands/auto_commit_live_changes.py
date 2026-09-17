from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import NotFoundError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.application.commands.create_commit import (
    CreateCommitCommand,
    CreateCommitHandler,
)
from app.modules.versioning.application.queries.scan_live_changes import (
    extract_classified_changes,
)
from app.modules.versioning.domain.entities import ImportReview
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import ImportReviewStatus, Tree
from app.modules.versioning.infrastructure.manifest_builder import ManifestBuilder


class AutoCommitLiveChangesCommand(Command):
    server_id: str
    branch: str = "main"


class AutoCommitLiveChangesHandler(CommandHandler[AutoCommitLiveChangesCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: AutoCommitLiveChangesCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None and self._versioning_repo is not None:
            return await self._execute(command, self._server_repo, self._versioning_repo)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with database.session_factory() as session:
                    server_repo = self._server_repo or SQLServerRepository(session)
                    versioning_repo = self._versioning_repo or SQLVersioningRepository(session)
                    res = await self._execute(command, server_repo, versioning_repo)
                    await session.commit()
                return res
            except Exception as exc:
                is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if is_lock and attempt < max_retries - 1:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                raise

        return CommandResult(success=False, error="Database retry exhausted")

    async def _execute(
        self,
        command: AutoCommitLiveChangesCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> CommandResult:
        from app.modules.shared.value_objects import ServerId

        try:
            server = await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        branch = await versioning_repo.get_branch_by_name(command.server_id, command.branch)
        if branch is None:
            raise NotFoundError(
                f"Branch '{command.branch}' not found on server '{command.server_id}'"
            )

        server_dir = (
            server.deployment.server_directory()
            if server.deployment
            else getattr(server, "root_path", "")
        )
        if not server_dir or not Path(server_dir).is_dir():
            return CommandResult(
                success=True,
                data={"commit_id": None, "review_id": None, "changes": []},
            )

        live_manifest = ManifestBuilder.build_manifest(
            server_dir=server_dir,
            server_type=getattr(server, "server_type", "vanilla"),
            minecraft_version=getattr(server, "minecraft_version", "1.21.1"),
        )
        live_tree = Tree.from_manifest(live_manifest)

        # Compare with branch head
        previous_head_commit_id = branch.head_commit_id
        if previous_head_commit_id:
            head_commit = await versioning_repo.get_commit(previous_head_commit_id)
            source_tree = (
                head_commit.tree
                if head_commit
                else Tree(server_type="vanilla", minecraft_version="1.21.1")
            )
        else:
            source_tree = Tree(server_type="vanilla", minecraft_version="1.21.1")


        changes = extract_classified_changes(source_tree, live_tree)
        if not changes:
            return CommandResult(
                success=True,
                data={"commit_id": None, "review_id": None, "changes": []},
            )

        # Execute CreateCommitCommand
        create_commit_handler = CreateCommitHandler(
            server_repo=server_repo,
            versioning_repo=versioning_repo,
            event_bus=self._event_bus,
        )
        commit_res = await create_commit_handler.handle(
            CreateCommitCommand(
                server_id=command.server_id,
                branch_name=command.branch,
                message=f"[auto-import] {len(changes)} live change(s) imported",
                author_id="onx-auto-import",
            )
        )
        if not commit_res.success:
            return commit_res

        new_commit_id = commit_res.entity_id or commit_res.details.get("commit_id")

        review = ImportReview(
            id=str(uuid.uuid4()),
            server_id=command.server_id,
            commit_id=new_commit_id,
            parent_commit_id=previous_head_commit_id,
            branch_name=command.branch,
            status=ImportReviewStatus.PENDING,
            changes=changes,
        )
        await versioning_repo.save_import_review(review)

        return CommandResult(
            success=True,
            data={
                "commit_id": new_commit_id,
                "review_id": review.id,
                "changes": changes,
            },
        )
