from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ConflictError, InvalidValueError
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.security import hash_api_key, hash_password
from app.modules.auth.domain.aggregate import Role, User
from app.modules.auth.infrastructure.jwt import create_access_token, create_refresh_token
from app.modules.auth.infrastructure.models import RefreshTokenModel
from app.modules.auth.infrastructure.permissions import PermissionEvaluator
from app.modules.auth.infrastructure.repository import SQLInvitationRepository, SQLUserRepository
from app.modules.server.infrastructure.repository import (
    SQLServerMembershipRepository,
)
from app.modules.shared.value_objects import EmailAddress, Permission, RoleId, UserId, Username


class AcceptInviteCommand(Command):
    token: str
    username: str | None = None
    email: str | None = None
    password: str
    display_name: str | None = None


class AcceptInviteHandler(CommandHandler[AcceptInviteCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._perm_evaluator = PermissionEvaluator()

    async def handle(self, command: AcceptInviteCommand) -> CommandResult:
        if len(command.password) < 8:
            raise InvalidValueError(
                "password", "too short", "Password must be at least 8 characters"
            )

        raw_username = (command.username or command.email or "").strip()
        try:
            username_vo = Username(raw_username)
        except ValueError as e:
            raise InvalidValueError("username", raw_username, str(e)) from e

        raw_email = command.email.strip() if command.email and command.email.strip() else None
        email_vo: EmailAddress | None = None
        if raw_email is not None:
            try:
                email_vo = EmailAddress(raw_email)
            except ValueError as e:
                raise InvalidValueError("email", raw_email, str(e)) from e

        token_hash = hashlib.sha256(command.token.encode("utf-8")).hexdigest()

        async with UnitOfWork(self._event_bus) as uow:
            invite_repo = SQLInvitationRepository(uow.session)
            invitation = await invite_repo.get_by_token_hash(token_hash)
            if invitation is None or not invitation.is_valid:
                raise InvalidValueError(
                    "token", command.token, "Invalid, expired, or revoked invitation token"
                )

            if invitation.email:
                effective_email = raw_email or ""
                if effective_email.lower() != invitation.email.lower():
                    raise InvalidValueError(
                        "email",
                        command.email,
                        "Invitation email does not match token destination",
                    )

            consumed = await invite_repo.atomic_consume(invitation.invitation_id)
            if not consumed:
                raise InvalidValueError(
                    "token", command.token, "Invitation token could not be consumed"
                )

            user_repo = SQLUserRepository(uow.session)
            if await user_repo.get_by_username(str(username_vo)):
                raise ConflictError("Username already registered")
            if email_vo is not None and await user_repo.get_by_email(str(email_vo)):
                raise ConflictError("Email already registered")

            role_name = invitation.global_role or "member"
            assigned_role = await user_repo.get_role_by_name(role_name)
            if assigned_role is None:
                canonical_perms: dict[str, list[Permission]] = {
                    "member": [Permission("user", "read"), Permission("server", "create")],
                }
                assigned_role = Role(
                    role_id=RoleId(uuid.uuid4().hex),
                    name=role_name,
                    permissions=canonical_perms.get(role_name, []),
                    description=f"Global {role_name} role",
                )
                await user_repo.save_role(assigned_role)

            resolved_display = (command.display_name or "").strip() or str(username_vo)
            user = User.create(
                user_id=UserId(uuid.uuid4().hex),
                username=str(username_vo),
                email=email_vo,
                password_hash=hash_password(command.password),
                display_name=resolved_display,
            )
            user.add_role(assigned_role)
            await user_repo.save(user)

            if invitation.server_id and invitation.server_role:
                server_repo = SQLServerMembershipRepository(uow.session)
                await server_repo.add_membership(
                    id=uuid.uuid4().hex,
                    server_id=invitation.server_id,
                    user_id=str(user.user_id),
                    role=invitation.server_role,
                )

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
                "user_id": str(user.user_id),
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": 900,
            },
        )
