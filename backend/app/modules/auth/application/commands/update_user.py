from __future__ import annotations

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import InvalidValueError
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import EmailAddress, UserId


class UpdateUserCommand(Command):
    user_id: str
    email: str | None = None
    display_name: str | None = None
    is_active: bool | None = None


class UpdateUserHandler(CommandHandler[UpdateUserCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: UpdateUserCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLUserRepository(uow.session)
            user = await repo.get(UserId(command.user_id))

            if command.email is not None:
                try:
                    user.set_email(EmailAddress(command.email))
                except ValueError as e:
                    raise InvalidValueError("email", command.email, str(e))
            if command.display_name is not None:
                user.set_display_name(command.display_name)
            if command.is_active is not None:
                if not command.is_active:
                    user.deactivate()

            await repo.save(user)
            for event in user.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "user_id": str(user.user_id),
                "email": str(user.email),
                "display_name": user.display_name,
                "is_active": user.is_active,
                "roles": [r.name for r in user.roles],
                "created_at": user.created_at,
                "last_login_at": user.last_login_at,
            },
        )
