from __future__ import annotations

from sqlalchemy import update

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ConflictError, InvalidValueError, PermissionDenied
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.auth.infrastructure.models import ApiKeyModel
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import EmailAddress, UserId, Username


class UpdateUserCommand(Command):
    user_id: str
    username: str | None = None
    email: str | None = None
    display_name: str | None = None
    is_active: bool | None = None
    requester_id: str | None = None
    requester_roles: list[str] | None = None
    requester_permissions: list[str] | None = None


class UpdateUserHandler(CommandHandler[UpdateUserCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: UpdateUserCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLUserRepository(uow.session)
            user = await repo.get(UserId(command.user_id))

            if command.requester_roles is not None:
                requester_roles = {str(r).lower() for r in command.requester_roles}
                target_is_owner = any(r.name.lower() == "owner" for r in user.roles)
                if target_is_owner and "owner" not in requester_roles:
                    raise PermissionDenied(
                        "Only an instance Owner can modify an Owner account"
                    )

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
                    if any(r.name == "owner" for r in user.roles):
                        all_users = await repo.list()
                        other_active_owners = [
                            u
                            for u in all_users
                            if str(u.user_id) != str(user.user_id)
                            and u.is_active
                            and any(r.name == "owner" for r in u.roles)
                        ]
                        if not other_active_owners:
                            raise ConflictError("Cannot deactivate the last active instance owner")
                    user.deactivate()

            if command.is_active is False:
                for api_key in user.api_keys:
                    if not api_key.is_revoked:
                        api_key.revoke(str(user.user_id))

            await repo.save(user)
            if command.is_active is False:
                await uow.session.execute(
                    update(ApiKeyModel)
                    .where(
                        ApiKeyModel.user_id == str(user.user_id),
                        ApiKeyModel.is_revoked.is_(False),
                    )
                    .values(is_revoked=True)
                )
            for event in user.collect_events():
                uow.add_event(event)
            await uow.commit()

        from app.websocket.endpoint import disconnect_user_sessions, revalidate_user_sessions

        if command.is_active is False:
            await disconnect_user_sessions(str(user.user_id), reason="Account deactivated")
        else:
            await revalidate_user_sessions(str(user.user_id))

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
