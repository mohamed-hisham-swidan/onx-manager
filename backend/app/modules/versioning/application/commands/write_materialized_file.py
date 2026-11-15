from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import (
    MaterializationMode,
    MaterializationStatus,
    PathClassification,
)
from app.modules.versioning.infrastructure.fs_atomic import atomic_write_file


class WriteMaterializedFileCommand(Command):
    materialization_id: str
    server_id: str
    path: str
    content: str


class WriteMaterializedFileHandler(CommandHandler[WriteMaterializedFileCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: WriteMaterializedFileCommand) -> CommandResult:
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
        command: WriteMaterializedFileCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> CommandResult:
        _ = server_repo
        materialization = await versioning_repo.get_materialization(command.materialization_id)
        if materialization is None or (
            materialization.server_id and materialization.server_id != command.server_id
        ):
            raise NotFoundError(
                f"Materialization '{command.materialization_id}' not found on server "
                f"'{command.server_id}'"
            )

        if materialization.status == MaterializationStatus.REMOVED:
            raise ConflictError(
                f"Cannot write to removed materialization '{command.materialization_id}'"
            )

        if materialization.mode != MaterializationMode.EDITABLE:
            raise ConflictError(
                f"Materialization '{command.materialization_id}' is read-only "
                f"(mode={materialization.mode})"
            )


        # Path traversal guard
        norm_path = os.path.normpath(command.path).replace("\\", "/")
        if norm_path.startswith("..") or os.path.isabs(command.path):
            raise ValidationError(f"Path escapes materialization root: {command.path}")

        # Classification check: TRACKED files only (ADR-0016)
        classification = materialization.path_classification.get(norm_path)
        if classification is None:
            # Check if it starts with a persistent or generated directory
            first_segment = norm_path.split("/")[0]
            if first_segment in ("world", "world_nether", "world_the_end"):
                classification = PathClassification.PERSISTENT
            elif first_segment in ("logs", "crash-reports"):
                classification = PathClassification.GENERATED
            elif first_segment == ".onx":
                classification = PathClassification.IGNORED
            else:
                classification = PathClassification.TRACKED

        if classification != PathClassification.TRACKED:
            raise ValidationError(
                f"Write to non-tracked path '{command.path}' rejected: "
                f"classification '{classification}' (see ADR-0016)"
            )

        dest_file = (Path(materialization.root_path) / norm_path).resolve()
        resolved_root = Path(materialization.root_path).resolve()
        if not dest_file.is_relative_to(resolved_root):
            raise ValidationError(f"Path escapes materialization root: {command.path}")

        bytes_written = atomic_write_file(dest_file, command.content)

        # Update path classification if new tracked file
        if norm_path not in materialization.path_classification:
            materialization.path_classification[norm_path] = PathClassification.TRACKED
            await versioning_repo.save_materialization(materialization)

        return CommandResult(
            success=True,
            data={"path": norm_path, "bytes_written": bytes_written},
        )
