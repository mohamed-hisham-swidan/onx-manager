from __future__ import annotations

import uuid

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.security import hash_password
from app.modules.auth.domain.aggregate import User
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import EmailAddress, UserId
from app.storage.unit_of_work import UnitOfWork


class CreateUserCommand(Command):
    email: str
    password: str
    display_name: str


class CreateUserHandler(CommandHandler[CreateUserCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: CreateUserCommand) -> CommandResult:
        from app.core.exceptions import ConflictError, InvalidValueError

        if len(command.password) < 8:
            raise InvalidValueError("password", "too short", "Password must be at least 8 characters")

        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLUserRepository(uow.session)
            existing = await repo.get_by_email(command.email)
            if existing:
                raise ConflictError("Email already registered")

            user = User.create(
                user_id=UserId(uuid.uuid4().hex),
                email=EmailAddress(command.email),
                password_hash=hash_password(command.password),
                display_name=command.display_name,
            )
            await repo.save(user)
            for event in user.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data={
            "user_id": str(user.user_id),
            "email": str(user.email),
            "display_name": user.display_name,
            "is_active": user.is_active,
            "roles": [r.name for r in user.roles],
            "created_at": user.created_at,
            "last_login_at": user.last_login_at,
        })
