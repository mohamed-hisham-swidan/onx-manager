from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import NotFoundError, ValidationError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.entities import Materialization
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import (
    MaterializationMode,
    MaterializationStatus,
    PathClassification,
    Revision,
)
from app.modules.versioning.infrastructure.tree_writer import write_tree_to_dir


class CreateMaterializationCommand(Command):
    server_id: str
    revision_type: str  # "commit" | "branch" | "tag"
    ref: str  # commit_id, branch_name, or tag_name
    mode: str = "readonly"  # "readonly" | "editable"


class CreateMaterializationHandler(CommandHandler[CreateMaterializationCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: CreateMaterializationCommand) -> CommandResult:
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
        command: CreateMaterializationCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> CommandResult:
        from app.modules.shared.value_objects import ServerId

        try:
            server = await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        # 1. Resolve Revision
        rev_type = command.revision_type.lower()
        if rev_type == "commit":
            commit = await versioning_repo.get_commit(command.ref)
            if commit is None or commit.server_id != command.server_id:
                raise NotFoundError(
                    f"Commit '{command.ref}' not found on server '{command.server_id}'"
                )
            revision = Revision.from_commit(commit.id, command.server_id)
        elif rev_type == "branch":
            branch = await versioning_repo.get_branch_by_name(command.server_id, command.ref)
            if branch is None or not branch.head_commit_id:
                raise NotFoundError(
                    f"Branch '{command.ref}' not found on server '{command.server_id}'"
                )
            commit = await versioning_repo.get_commit(branch.head_commit_id)
            if commit is None:
                raise NotFoundError(
                    f"Head commit '{branch.head_commit_id}' for branch '{command.ref}' not found"
                )
            revision = Revision.from_branch(
                branch.name,
                branch.head_commit_id,
                branch.server_id,
                command.server_id,
            )
        elif rev_type == "tag":
            tag = await versioning_repo.get_tag(command.server_id, command.ref)
            if tag is None:
                raise NotFoundError(
                    f"Tag '{command.ref}' not found on server '{command.server_id}'"
                )
            commit = await versioning_repo.get_commit(tag.commit_id)
            if commit is None:
                raise NotFoundError(f"Commit '{tag.commit_id}' for tag '{command.ref}' not found")
            revision = Revision.from_tag(
                tag.name,
                tag.commit_id,
                tag.server_id,
                command.server_id,
            )
        else:
            raise ValidationError(f"Unsupported revision_type: '{command.revision_type}'")

        # 2. Allocate worktree path
        server_dir = (
            server.deployment.server_directory()
            if server.deployment
            else getattr(server, "root_path", "")
        )

        if not server_dir:
            server_dir = f"/srv/minecraft/{command.server_id}"

        mat_id = str(uuid.uuid4())
        worktree_root = os.path.normpath(
            os.path.join(server_dir, ".onx", "worktrees", mat_id)
        )

        mode = (
            MaterializationMode.EDITABLE
            if command.mode.lower() == "editable"
            else MaterializationMode.READONLY
        )

        # 3. Path classification map
        path_classification: dict[str, PathClassification] = {}
        tree = commit.tree
        for p in tree.configs:
            norm_p = os.path.normpath(p).replace("\\", "/")
            path_classification[norm_p] = PathClassification.TRACKED
        for m in tree.mods:
            if isinstance(m, dict) and m.get("filename"):
                norm_m = os.path.normpath(m["filename"]).replace("\\", "/")
                path_classification[norm_m] = PathClassification.TRACKED

        for p_dir in ["world", "world_nether", "world_the_end"]:
            path_classification[p_dir] = PathClassification.PERSISTENT
        for g_dir in ["logs", "crash-reports"]:
            path_classification[g_dir] = PathClassification.GENERATED
        path_classification[".onx"] = PathClassification.IGNORED

        materialization = Materialization(
            id=mat_id,
            commit_id=commit.id,
            root_path=worktree_root,
            status=MaterializationStatus.PENDING,
            path_classification=path_classification,
            mode=mode,
            server_id=command.server_id,
            revision=revision.resolved_from,
        )

        # 4. Write tree to disk and verify
        write_tree_to_dir(
            tree=commit.tree,
            target_root=worktree_root,
            server_dir=server_dir if Path(server_dir).is_dir() else None,
            verify=True,
        )

        # 5. Mark ready and persist
        materialization.mark_ready()
        await versioning_repo.save_materialization(materialization)

        return CommandResult(
            success=True,
            data={
                "id": materialization.id,
                "materialization_id": materialization.id,
                "revision": materialization.revision,
                "mode": materialization.mode.value,
                "status": materialization.status.value,
                "root": materialization.root_path,
                "root_path": materialization.root_path,
                "commit_id": materialization.commit_id,
            },
        )
