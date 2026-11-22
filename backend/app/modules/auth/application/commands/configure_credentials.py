from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ConflictError, InvalidValueError, NotFoundError
from app.core.local_auth import LOCAL_ADMIN_USER_ID, LOCAL_ADMIN_USERNAME
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.security import hash_api_key, hash_password
from app.modules.auth.domain.aggregate import Role, User
from app.modules.auth.infrastructure.jwt import create_access_token, create_refresh_token
from app.modules.auth.infrastructure.models import RefreshTokenModel
from app.modules.auth.infrastructure.permissions import PermissionEvaluator
from app.modules.auth.infrastructure.repository import (
    SQLSystemStateRepository,
    SQLUserRepository,
)
from app.modules.shared.value_objects import (
    EmailAddress,
    Permission,
    RoleId,
    UserId,
    Username,
)


class ConfigureCredentialsCommand(Command):
    actor_user_id: str
    username: str
    password: str
    display_name: str | None = None
    email: str | None = None


class ConfigureCredentialsHandler(CommandHandler[ConfigureCredentialsCommand]):
    """Upgrade a passwordless local-admin account to explicit username + password auth."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._perm_evaluator = PermissionEvaluator()

    async def handle(self, command: ConfigureCredentialsCommand) -> CommandResult:
        if len(command.password) < 8:
            raise InvalidValueError(
                "password", "too short", "Password must be at least 8 characters"
            )

        try:
            username_vo = Username(command.username)
        except ValueError as e:
            raise InvalidValueError("username", command.username, str(e)) from e

        email_vo: EmailAddress | None = None
        if command.email and command.email.strip():
            try:
                email_vo = EmailAddress(command.email.strip())
            except ValueError as e:
                raise InvalidValueError("email", command.email, str(e)) from e

        async with UnitOfWork(self._event_bus) as uow:
            sys_repo = SQLSystemStateRepository(uow.session)
            state = await sys_repo.get_with_lock("default")
            if state.password_configured:
                raise ConflictError("Owner credentials are already configured")

            user_repo = SQLUserRepository(uow.session)
            user: User | None = None
            for candidate_id in dict.fromkeys([command.actor_user_id, LOCAL_ADMIN_USER_ID]):
                if not candidate_id:
                    continue
                try:
                    user = await user_repo.get(UserId(candidate_id))
                    break
                except NotFoundError:
                    continue
            if user is None:
                user = await user_repo.get_by_username(LOCAL_ADMIN_USERNAME)

            other_by_username = await user_repo.get_by_username(str(username_vo))
            if other_by_username is not None and (
                user is None or str(other_by_username.user_id) != str(user.user_id)
            ):
                raise ConflictError("Username already registered")

            if email_vo is not None:
                other_by_email = await user_repo.get_by_email(str(email_vo))
                if other_by_email is not None and (
                    user is None or str(other_by_email.user_id) != str(user.user_id)
                ):
                    raise ConflictError("Email already registered")

            owner_role = await user_repo.get_role_by_name("owner")
            if owner_role is None:
                owner_role = Role(
                    role_id=RoleId(uuid.uuid4().hex),
                    name="owner",
                    permissions=[Permission("admin", "full"), Permission("global", "*")],
                    description="Instance Owner",
                )
                await user_repo.save_role(owner_role)

            resolved_display = (command.display_name or "").strip() or str(username_vo)
            if user is None:
                user = User.create(
                    user_id=UserId(LOCAL_ADMIN_USER_ID),
                    username=str(username_vo),
                    email=email_vo,
                    password_hash=hash_password(command.password),
                    display_name=resolved_display,
                )
                user.add_role(owner_role)
            else:
                user.set_username(str(username_vo))
                user.set_password_hash(hash_password(command.password))
                user.set_display_name(resolved_display)
                user.set_email(email_vo)
                if not any(r.name == "owner" for r in user.roles):
                    user.add_role(owner_role)

            await user_repo.save(user)
            state.mark_password_configured()
            await sys_repo.save(state)

            for event in user.collect_events():
                uow.add_event(event)

            user_perms = await self._perm_evaluator.get_effective_permissions(user)
            scope = ",".join(str(p) for p in user_perms)
            access_token = create_access_token(
                user_id=str(user.user_id),
                roles=[r.name for r in user.roles],
                permissions=user_perms,
                scope=scope,
            )
            refresh_token = create_refresh_token()
            rt_model = RefreshTokenModel(
                user_id=str(user.user_id),
                token_hash=hash_api_key(refresh_token),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
            uow.session.add(rt_model)
            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "success": True,
                "message": "Credentials configured successfully",
                "user_id": str(user.user_id),
                "username": user.username,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": 900,
            },
        )
