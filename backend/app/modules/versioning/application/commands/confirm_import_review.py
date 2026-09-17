from __future__ import annotations

import asyncio

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.repository import VersioningRepository


class ConfirmImportReviewCommand(Command):
    review_id: str
    server_id: str


class ConfirmImportReviewHandler(CommandHandler[ConfirmImportReviewCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: ConfirmImportReviewCommand) -> CommandResult:
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
        command: ConfirmImportReviewCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> CommandResult:
        _ = server_repo
        review = await versioning_repo.get_import_review(command.review_id)
        if review is None or (review.server_id and review.server_id != command.server_id):
            raise NotFoundError(
                f"Import review '{command.review_id}' not found on server '{command.server_id}'"
            )

        if review.is_terminal:
            raise ConflictError(
                f"Cannot confirm terminal import review '{command.review_id}' "
                f"(status={review.status})"
            )

        review.confirm()
        await versioning_repo.save_import_review(review)

        return CommandResult(success=True, data={"status": "confirmed"})

