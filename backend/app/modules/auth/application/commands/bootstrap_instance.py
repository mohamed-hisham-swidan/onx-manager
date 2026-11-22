from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ConflictError, InvalidValueError
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.security import hash_api_key, hash_password
from app.modules.auth.domain.aggregate import AccessMode, Role, User
from app.modules.auth.infrastructure.jwt import create_access_token, create_refresh_token
from app.modules.auth.infrastructure.models import RefreshTokenModel
from app.modules.auth.infrastructure.permissions import PermissionEvaluator
from app.modules.auth.infrastructure.repository import SQLSystemStateRepository, SQLUserRepository
from app.modules.shared.value_objects import EmailAddress, Permission, RoleId, UserId, Username


class BootstrapInstanceCommand(Command):
    username: str | None = None
    email: str | None = None
    password: str
    display_name: str | None = None
    access_mode: str = "LOCAL"


class BootstrapInstanceHandler(CommandHandler[BootstrapInstanceCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._perm_evaluator = PermissionEvaluator()

    async def handle(self, command: BootstrapInstanceCommand) -> CommandResult:
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

        mode_str = command.access_mode.upper()
        if mode_str not in ("LOCAL", "GLOBAL"):
            raise InvalidValueError(
                "access_mode", command.access_mode, "Access mode must be LOCAL or GLOBAL"
            )

        async with UnitOfWork(self._event_bus) as uow:
            sys_repo = SQLSystemStateRepository(uow.session)
            state = await sys_repo.get_with_lock("default")

            if state.initialized:
                raise ConflictError("Instance is already initialized")

            user_repo = SQLUserRepository(uow.session)
            if await user_repo.get_by_username(str(username_vo)):
                raise ConflictError("Username already registered")
            if email_vo is not None and await user_repo.get_by_email(str(email_vo)):
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
            user = User.create(
                user_id=UserId(uuid.uuid4().hex),
                username=str(username_vo),
                email=email_vo,
                password_hash=hash_password(command.password),
                display_name=resolved_display,
            )
            user.add_role(owner_role)
            await user_repo.save(user)

            target_mode = AccessMode.GLOBAL if mode_str == "GLOBAL" else AccessMode.LOCAL
            state.mark_initialized(access_mode=target_mode, password_configured=True)
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
                "message": "Instance bootstrapped successfully",
                "user_id": str(user.user_id),
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": 900,
            },
        )
