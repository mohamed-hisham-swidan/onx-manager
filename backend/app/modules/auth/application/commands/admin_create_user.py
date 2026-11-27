from __future__ import annotations

import uuid

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ConflictError, InvalidValueError
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.security import hash_password
from app.modules.auth.application.access_policy import (
    apply_user_access_policy,
    build_user_profile_dict,
)
from app.modules.auth.domain.aggregate import User
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import EmailAddress, UserId, Username


class AdminCreateUserCommand(Command):
    username: str
    email: str | None = None
    password: str
    display_name: str | None = None
    role: str = "viewer"
    server_ids: list[str] = Field(default_factory=list)
    all_servers_access: bool = False
    denied_permissions: list[str] = Field(default_factory=list)
    is_active: bool = True
    requester_id: str | None = None
    requester_roles: list[str] | None = None


class AdminCreateUserHandler(CommandHandler[AdminCreateUserCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: AdminCreateUserCommand) -> CommandResult:
        if len(command.password) < 8:
            raise InvalidValueError(
                "password", "too short", "Password must be at least 8 characters"
            )

        raw_username = (command.username or "").strip()
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
            if not command.is_active:
                user.deactivate()
            await repo.save(user)

            await apply_user_access_policy(
                uow.session,
                repo,
                user,
                target_role=command.role,
                server_ids=command.server_ids,
                all_servers_access=command.all_servers_access,
                denied_permissions=command.denied_permissions,
                requester_roles=command.requester_roles,
                validate_servers_exist=True,
            )

            for event in user.collect_events():
                uow.add_event(event)
            await uow.commit()

            profile = await build_user_profile_dict(uow.session, str(user.user_id))

        return CommandResult(success=True, data=profile or {})
