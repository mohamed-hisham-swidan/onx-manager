from __future__ import annotations

import asyncio
import contextlib
import shutil
from pathlib import Path

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import NotFoundError, PathContainmentError
from app.core.fs_utils import assert_inside_root
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.repository import VersioningRepository


def _materializations_root(root_path: str) -> Path:
    """Return the ``.onx/tests`` or ``.onx/worktrees`` container of a materialization."""
    container = Path(root_path).parent
    if container.name not in ("tests", "worktrees") or container.parent.name != ".onx":
        raise PathContainmentError(root_path, "<server>/.onx/(tests|worktrees)")
    return container


class RemoveMaterializationCommand(Command):
    materialization_id: str
    server_id: str


class RemoveMaterializationHandler(CommandHandler[RemoveMaterializationCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: RemoveMaterializationCommand) -> CommandResult:
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
        command: RemoveMaterializationCommand,
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

        assert_inside_root(
            materialization.root_path, _materializations_root(materialization.root_path)
        )
        materialization.mark_removed()
        shutil.rmtree(materialization.root_path, ignore_errors=True)
        await versioning_repo.save_materialization(materialization)

        return CommandResult(success=True, data={"removed": True})


async def cleanup_server_materializations(
    server_id: str,
    event_bus: EventBus | None = None,
) -> None:
    """Best-effort cleanup of orphaned worktrees when a server is deleted."""
    from app.core.persistence.db import database
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

    async with database.session_factory() as session:
        server_repo = SQLServerRepository(session)
        versioning_repo = SQLVersioningRepository(session)
        handler = RemoveMaterializationHandler(
            server_repo=server_repo,
            versioning_repo=versioning_repo,
            event_bus=event_bus,
        )
        mats = await versioning_repo.list_materializations(server_id)
        for m in mats:
            with contextlib.suppress(Exception):
                await handler.handle(
                    RemoveMaterializationCommand(
                        materialization_id=m.id,
                        server_id=server_id,
                    )
                )
        await session.commit()

