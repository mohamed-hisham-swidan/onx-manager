from __future__ import annotations

import uuid

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.security import hash_password
from app.modules.auth.domain.aggregate import User
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import EmailAddress, UserId, Username


class CreateUserCommand(Command):
    username: str | None = None
    email: str | None = None
    password: str
    display_name: str | None = None


class CreateUserHandler(CommandHandler[CreateUserCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: CreateUserCommand) -> CommandResult:
        from app.core.exceptions import ConflictError, InvalidValueError

        if len(command.password) < 8:
            raise InvalidValueError(
                "password", "too short", "Password must be at least 8 characters"
            )

        raw_username = (command.username or command.email or "").strip()
        try:
            username_vo = Username(raw_username)
        except ValueError as e:
            raise InvalidValueError("username", raw_username, str(e)) from e

        email_vo: EmailAddress | None = None
        if command.email and command.email.strip():
            try:
                email_vo = EmailAddress(command.email.strip())
            except ValueError as e:
                raise InvalidValueError("email", command.email, str(e)) from e

        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLUserRepository(uow.session)
            if await repo.get_by_username(str(username_vo)):
                raise ConflictError("Username already registered")
            if email_vo is not None and await repo.get_by_email(str(email_vo)):
                raise ConflictError("Email already registered")

            resolved_display = (command.display_name or "").strip() or str(username_vo)
            user = User.create(
                user_id=UserId(uuid.uuid4().hex),
                username=str(username_vo),
                email=email_vo,
                password_hash=hash_password(command.password),
                display_name=resolved_display,
            )

            viewer_role = await repo.get_role_by_name("viewer")
            if viewer_role is None:
                from app.modules.auth.domain.aggregate import Role
                from app.modules.shared.value_objects import Permission, RoleId

                viewer_role = Role(
                    role_id=RoleId(uuid.uuid4().hex),
                    name="viewer",
                    permissions=[Permission("user", "read"), Permission("server", "read")],
                    description="Default Viewer role",
                )
                await repo.save_role(viewer_role)

            user.add_role(viewer_role)

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
