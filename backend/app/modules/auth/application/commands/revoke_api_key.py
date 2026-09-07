from __future__ import annotations

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import ApiKeyId, UserId


class RevokeApiKeyCommand(Command):
    user_id: str
    api_key_id: str


class RevokeApiKeyHandler(CommandHandler[RevokeApiKeyCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: RevokeApiKeyCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLUserRepository(uow.session)
            user = await repo.get(UserId(command.user_id))
            if user is None:
                return CommandResult(
                    success=False, error="User not found", error_code="NOT_FOUND"
                )
            target_id = ApiKeyId(command.api_key_id)
            if not any(k.api_key_id == target_id for k in user.api_keys):
                return CommandResult(
                    success=False, error="API key not found", error_code="NOT_FOUND"
                )
            user.revoke_api_key(target_id)
            await repo.save(user)
            for event in user.collect_events():
                uow.add_event(event)
            await uow.commit()
        return CommandResult(success=True, data={"revoked": True})
