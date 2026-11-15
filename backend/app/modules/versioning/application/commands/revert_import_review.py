from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.application.commands.create_commit import (
    CreateCommitCommand,
    CreateCommitHandler,
)
from app.modules.versioning.application.queries.scan_live_changes import (
    extract_classified_changes,
)
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import Tree
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_file
from app.modules.versioning.infrastructure.manifest_builder import ManifestBuilder


class RevertImportReviewCommand(Command):
    review_id: str
    server_id: str


class RevertImportReviewHandler(CommandHandler[RevertImportReviewCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: RevertImportReviewCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.application.mode_guard import ensure_versioning_allowed
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None:
            await ensure_versioning_allowed(command.server_id, server_repo=self._server_repo)

        if self._server_repo is not None and self._versioning_repo is not None:
            return await self._execute(command, self._server_repo, self._versioning_repo)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with database.session_factory() as session:
                    await ensure_versioning_allowed(command.server_id, session=session)
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
        command: RevertImportReviewCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> CommandResult:
        from app.modules.shared.value_objects import ServerId

        try:
            server = await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        review = await versioning_repo.get_import_review(command.review_id)
        if review is None or (review.server_id and review.server_id != command.server_id):
            raise NotFoundError(
                f"Import review '{command.review_id}' not found on server '{command.server_id}'"
            )

        if review.is_terminal:
            raise ConflictError(
                f"Cannot revert terminal import review '{command.review_id}' "
                f"(status={review.status})"
            )

        if not review.parent_commit_id:
            raise ConflictError(
                f"Import review '{command.review_id}' has no parent commit to revert to"
            )

        parent_commit = await versioning_repo.get_commit(review.parent_commit_id)
        if parent_commit is None:
            raise NotFoundError(
                f"Parent commit '{review.parent_commit_id}' not found on server "
                f"'{command.server_id}'"
            )


        auto_commit = await versioning_repo.get_commit(review.commit_id)
        if auto_commit is None:
            raise NotFoundError(
                f"Auto-commit '{review.commit_id}' not found on server '{command.server_id}'"
            )

        server_dir = (
            server.deployment.server_directory()
            if server.deployment
            else getattr(server, "root_path", "")
        )
        if not server_dir or not Path(server_dir).is_dir():
            raise NotFoundError(f"Server directory for '{command.server_id}' not found")

        # Revert racing check: ensure live dir has not diverged since auto-commit
        live_manifest = ManifestBuilder.build_manifest(
            server_dir=server_dir,
            server_type=getattr(server, "server_type", "vanilla"),
            minecraft_version=getattr(server, "minecraft_version", "1.21.1"),
        )
        live_tree = Tree.from_manifest(live_manifest)
        uncommitted_live_changes = extract_classified_changes(auto_commit.tree, live_tree)
        if uncommitted_live_changes:
            raise ConflictError(
                "Live filesystem has changed since auto-commit was created; "
                "resolve live changes before reverting"
            )

        # Restore tracked files from parent commit
        s_path = Path(server_dir).resolve()
        parent_tree = parent_commit.tree

        # 1. Configs
        auto_configs = auto_commit.tree.configs
        for rel_path in auto_configs:
            norm_rel = os.path.normpath(rel_path).replace("\\", "/")
            dest_file = s_path / norm_rel
            if norm_rel in parent_tree.configs:
                atomic_write_file(dest_file, parent_tree.configs[norm_rel])
            else:
                # File was newly added by auto_commit; remove it
                if dest_file.is_file():
                    dest_file.unlink(missing_ok=True)

        for rel_path, content in parent_tree.configs.items():
            norm_rel = os.path.normpath(rel_path).replace("\\", "/")
            dest_file = s_path / norm_rel
            if not dest_file.is_file():
                atomic_write_file(dest_file, content)

        # 2. Mods
        auto_mod_files = {m.get("filename") for m in auto_commit.tree.mods if m.get("filename")}
        parent_mod_files = {m.get("filename") for m in parent_tree.mods if m.get("filename")}
        for mod_f in auto_mod_files:
            if mod_f and mod_f not in parent_mod_files:
                norm_m = os.path.normpath(mod_f).replace("\\", "/")
                mod_path = s_path / norm_m
                if mod_path.is_file():
                    mod_path.unlink(missing_ok=True)

        # 3. Create revert commit
        create_commit_handler = CreateCommitHandler(
            server_repo=server_repo,
            versioning_repo=versioning_repo,
            event_bus=self._event_bus,
        )
        commit_res = await create_commit_handler.handle(
            CreateCommitCommand(
                server_id=command.server_id,
                branch_name=review.branch_name,
                message=f"[revert] Revert auto-import {review.commit_id[:8]}",
                author_id="onx-auto-revert",
            )
        )
        if not commit_res.success:
            return commit_res

        revert_commit_id = commit_res.entity_id or commit_res.details.get("commit_id")
        review.revert(revert_commit_id=revert_commit_id)
        await versioning_repo.save_import_review(review)

        return CommandResult(
            success=True,
            data={"status": "reverted", "revert_commit_id": revert_commit_id},
        )
