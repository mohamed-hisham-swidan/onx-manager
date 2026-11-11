from __future__ import annotations

import asyncio

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import (
    MaterializationMode,
    MaterializationStatus,
)


class SetMaterializationEditModeCommand(Command):
    materialization_id: str
    server_id: str
    enabled: bool


class SetMaterializationEditModeHandler(
    CommandHandler[SetMaterializationEditModeCommand]
):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: SetMaterializationEditModeCommand) -> CommandResult:
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
        command: SetMaterializationEditModeCommand,
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
                f"Cannot change edit mode on removed materialization '{command.materialization_id}'"
            )

        new_mode = (
            MaterializationMode.EDITABLE
            if command.enabled
            else MaterializationMode.READONLY
        )
        materialization.set_mode(new_mode)
        await versioning_repo.save_materialization(materialization)

        return CommandResult(success=True, data={"mode": new_mode.value})
