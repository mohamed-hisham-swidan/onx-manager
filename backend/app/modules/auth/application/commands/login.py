from __future__ import annotations

from datetime import UTC, datetime

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import AuthenticationError, InvalidCredentialsError
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.security import verify_password
from app.modules.auth.infrastructure.audit import AuditLogger
from app.modules.auth.infrastructure.jwt import (
    create_access_token,
    create_refresh_token,
)
from app.modules.auth.infrastructure.models import RefreshTokenModel
from app.modules.auth.infrastructure.permissions import PermissionEvaluator
from app.modules.auth.infrastructure.repository import SQLUserRepository


class LoginCommand(Command):
    email: str
    password: str
    ip_address: str = ""


class LoginHandler(CommandHandler[LoginCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._perm_evaluator = PermissionEvaluator()

    async def handle(self, command: LoginCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLUserRepository(uow.session)
            user = await repo.get_by_email(command.email)
            if user is None:
                raise InvalidCredentialsError()
            if not user.is_active:
                raise AuthenticationError("Account is deactivated")
            if not verify_password(command.password, user.password_hash):
                raise InvalidCredentialsError()

            user.record_login(ip_address=command.ip_address)
            await repo.save(user)
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
            from datetime import timedelta

            from app.core.security import hash_api_key

            rt_model = RefreshTokenModel(
                user_id=str(user.user_id),
                token_hash=hash_api_key(refresh_token),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
            uow.session.add(rt_model)

            audit = AuditLogger(uow.session)
            await audit.log(
                action="user.login",
                actor_type="user",
                actor_id=str(user.user_id),
                resource_type="session",
                resource_id=str(user.user_id),
                outcome="success",
                ip_address=command.ip_address or None,
            )

            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": 900,
                "user_id": str(user.user_id),
                "display_name": user.display_name,
                "roles": [r.name for r in user.roles],
                "permissions": user_perms,
            },
        )
