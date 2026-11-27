from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import Field

from app.core.authorization import ROLE_ADMIN, ROLE_OWNER, resolve_primary_role
from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import InvalidValueError, PermissionDenied
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.auth.application.access_policy import resolve_invite_policy
from app.modules.auth.domain.aggregate import Invitation
from app.modules.auth.infrastructure.repository import SQLInvitationRepository, SQLUserRepository
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import UserId


class CreateInviteCommand(Command):
    creator_id: str
    email: str | None = None
    role: str | None = None
    global_role: str | None = None
    server_id: str | None = None
    server_ids: list[str] = Field(default_factory=list)
    server_role: str | None = None
    all_servers_access: bool = False
    denied_permissions: list[str] = Field(default_factory=list)
    max_uses: int = 1
    expires_in_hours: int | None = 48


class CreateInviteHandler(CommandHandler[CreateInviteCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: CreateInviteCommand) -> CommandResult:
        target_role, merged_server_ids, effective_all_servers, denied_caps = (
            resolve_invite_policy(
                role=command.role,
                global_role=command.global_role,
                server_role=command.server_role,
                server_id=command.server_id,
                server_ids=command.server_ids,
                all_servers_access=command.all_servers_access,
                denied_permissions=command.denied_permissions,
            )
        )

        raw_secret = secrets.token_urlsafe(24)
        raw_token = f"mcis_{raw_secret}"
        token_prefix = raw_token[:10]
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

        expires_at = (
            datetime.now(UTC) + timedelta(hours=command.expires_in_hours)
            if command.expires_in_hours
            else None
        )

        invitation_id = f"inv_{uuid.uuid4().hex}"
        legacy_server_role = (
            "server_admin"
            if target_role == "server_admin"
            else ("viewer" if target_role == "viewer" else None)
        )

        invitation = Invitation(
            invitation_id=invitation_id,
            token_hash=token_hash,
            token_prefix=token_prefix,
            creator_id=command.creator_id,
            email=command.email,
            global_role=target_role,
            server_id=merged_server_ids[0] if merged_server_ids else None,
            server_role=legacy_server_role,
            server_ids=merged_server_ids,
            denied_permissions=denied_caps,
            all_servers_access=effective_all_servers,
            max_uses=command.max_uses,
            expires_at=expires_at,
        )

        async with UnitOfWork(self._event_bus) as uow:
            user_repo = SQLUserRepository(uow.session)
            creator = (
                await user_repo.get(UserId(command.creator_id)) if command.creator_id else None
            )
            if creator is None:
                raise PermissionDenied("Invalid or missing invitation creator")

            creator_role_names = [r.name for r in creator.roles]
            creator_primary = resolve_primary_role(creator_role_names)
            is_owner = creator_primary == ROLE_OWNER or any(
                r.has_permission("global", "*") for r in creator.roles
            )
            is_global_admin = (
                is_owner
                or creator_primary == ROLE_ADMIN
                or any(r.has_permission("admin", "full") for r in creator.roles)
            )

            if not is_global_admin:
                raise PermissionDenied("Only instance Owners or Admins can create invitations")

            if target_role == ROLE_OWNER and not is_owner:
                raise PermissionDenied(
                    "Cannot create invitation with role 'owner' without owner privileges"
                )

            if merged_server_ids:
                server_repo = SQLServerRepository(uow.session)
                for sid in merged_server_ids:
                    server = await server_repo.get(sid)
                    if server is None:
                        raise InvalidValueError("server_ids", sid, f"Server '{sid}' not found")

            repo = SQLInvitationRepository(uow.session)
            await repo.save(invitation)
            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "invite_id": invitation_id,
                "token": raw_token,
                "token_prefix": token_prefix,
                "email": command.email,
                "role": target_role,
                "global_role": target_role,
                "server_id": invitation.server_id,
                "server_ids": merged_server_ids,
                "server_role": legacy_server_role,
                "all_servers_access": effective_all_servers,
                "denied_permissions": denied_caps,
                "status": invitation.status.value,
                "max_uses": invitation.max_uses,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )
