from __future__ import annotations

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import UserId
from app.core.persistence.unit_of_work import UnitOfWork


class DeleteUserCommand(Command):
    user_id: str


class DeleteUserHandler(CommandHandler[DeleteUserCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: DeleteUserCommand) -> CommandResult:
        from app.core.exceptions import NotFoundError

        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLUserRepository(uow.session)
            try:
                user = await repo.get(UserId(command.user_id))
            except NotFoundError:
                return CommandResult(success=False, error="User not found", error_code="NOT_FOUND")
            await repo.delete(UserId(command.user_id))
            for event in user.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data={})
