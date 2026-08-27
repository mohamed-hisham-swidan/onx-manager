from __future__ import annotations

from datetime import UTC

from sqlalchemy import select

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.security import hash_api_key
from app.modules.auth.infrastructure.models import RefreshTokenModel


class LogoutCommand(Command):
    user_id: str
    refresh_token: str = ""


class LogoutHandler(CommandHandler[LogoutCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: LogoutCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            if command.refresh_token:
                token_hash = hash_api_key(command.refresh_token)
                stmt = select(RefreshTokenModel).where(
                    RefreshTokenModel.token_hash == token_hash,
                    RefreshTokenModel.is_revoked == False,
                )
                result = await uow.session.execute(stmt)
                rt = result.scalar_one_or_none()
                if rt:
                    from datetime import datetime

                    rt.is_revoked = True
                    rt.revoked_at = datetime.now(UTC)
            await uow.commit()
        return CommandResult(success=True, data={"logout": True})
