from __future__ import annotations

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ConflictError, InvalidValueError
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import EmailAddress, UserId, Username


class UpdateUserCommand(Command):
    user_id: str
    username: str | None = None
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

            if command.username is not None:
                try:
                    username_vo = Username(command.username)
                except ValueError as e:
                    raise InvalidValueError("username", command.username, str(e)) from e
                existing_u = await repo.get_by_username(str(username_vo))
                if existing_u is not None and str(existing_u.user_id) != str(user.user_id):
                    raise ConflictError("Username already registered")
                user.set_username(str(username_vo))

            if command.email is not None:
                cleaned_email = command.email.strip()
                if cleaned_email == "":
                    user.set_email(None)
                else:
                    try:
                        email_vo = EmailAddress(cleaned_email)
                    except ValueError as e:
                        raise InvalidValueError("email", command.email, str(e)) from e
                    existing_e = await repo.get_by_email(str(email_vo))
                    if existing_e is not None and str(existing_e.user_id) != str(user.user_id):
                        raise ConflictError("Email already registered")
                    user.set_email(email_vo)
            if command.display_name is not None:
                user.set_display_name(command.display_name)
            if command.is_active is not None:
                if command.is_active:
                    user.activate()
                else:
                    user.deactivate()

            await repo.save(user)
            for event in user.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "user_id": str(user.user_id),
                "username": user.username,
                "email": str(user.email) if user.email is not None else None,
                "display_name": user.display_name,
                "is_active": user.is_active,
                "roles": [r.name for r in user.roles],
                "created_at": user.created_at,
                "last_login_at": user.last_login_at,
            },
        )
