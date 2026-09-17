from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import AuthenticationError
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.security import hash_api_key
from app.modules.auth.infrastructure.jwt import (
    create_access_token,
    create_refresh_token,
)
from app.modules.auth.infrastructure.models import RefreshTokenModel
from app.modules.auth.infrastructure.permissions import PermissionEvaluator
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import UserId


class RefreshTokenCommand(Command):
    refresh_token: str


class RefreshTokenHandler(CommandHandler[RefreshTokenCommand]):
    _lock = asyncio.Lock()

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._perm_evaluator = PermissionEvaluator()

    async def handle(self, command: RefreshTokenCommand) -> CommandResult:
        token_hash = hash_api_key(command.refresh_token)
        async with self._lock, UnitOfWork(self._event_bus) as uow:
            stmt = (
                select(RefreshTokenModel)
                .where(
                    RefreshTokenModel.token_hash == token_hash,
                    RefreshTokenModel.is_revoked == False,
                )
                .with_for_update()
            )
            result = await uow.session.execute(stmt)
            rt = result.scalar_one_or_none()
            if rt is None:
                raise AuthenticationError("Invalid or revoked refresh token")
            now_naive = datetime.now(UTC).replace(tzinfo=None)
            expires = rt.expires_at
            if expires and expires.tzinfo is not None:
                expires = expires.replace(tzinfo=None)
            if expires and now_naive > expires:
                raise AuthenticationError("Refresh token has expired")
            rt.is_revoked = True
            rt.revoked_at = datetime.now(UTC)

            repo = SQLUserRepository(uow.session)
            user = await repo.get(UserId(rt.user_id))
            if not user.is_active:
                raise AuthenticationError("Account is deactivated")

            new_refresh_token = create_refresh_token()
            from datetime import timedelta

            new_rt = RefreshTokenModel(
                user_id=str(user.user_id),
                token_hash=hash_api_key(new_refresh_token),
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
            uow.session.add(new_rt)

            user_perms = await self._perm_evaluator.get_effective_permissions(user)
            scope = ",".join(str(p) for p in user_perms)
            access_token = create_access_token(
                user_id=str(user.user_id),
                roles=[r.name for r in user.roles],
                permissions=user_perms,
                scope=scope,
            )
            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "access_token": access_token,
                "refresh_token": new_refresh_token,
                "token_type": "bearer",
                "expires_in": 900,
            },
        )
