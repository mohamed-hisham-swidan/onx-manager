from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import uuid

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import InvalidValueError, PermissionDenied
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.auth.domain.aggregate import Invitation
from app.modules.auth.infrastructure.repository import SQLInvitationRepository, SQLUserRepository
from app.modules.server.infrastructure.repository import SQLServerMembershipRepository, SQLServerRepository
from app.modules.shared.value_objects import UserId


class CreateInviteCommand(Command):
    creator_id: str
    email: str | None = None
    global_role: str = "member"
    server_id: str | None = None
    server_role: str | None = None
    max_uses: int = 1
    expires_in_hours: int | None = 48


class CreateInviteHandler(CommandHandler[CreateInviteCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: CreateInviteCommand) -> CommandResult:
        if command.server_role and command.server_role not in ("admin", "dev", "viewer"):
            raise InvalidValueError("server_role", command.server_role, "Server role must be admin, dev, or viewer")

        raw_secret = secrets.token_urlsafe(24)
        raw_token = f"mcis_{raw_secret}"
        token_prefix = raw_token[:10]
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

        expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=command.expires_in_hours)
            if command.expires_in_hours
            else None
        )

        invitation_id = f"inv_{uuid.uuid4().hex}"

        invitation = Invitation(
            invitation_id=invitation_id,
            token_hash=token_hash,
            token_prefix=token_prefix,
            creator_id=command.creator_id,
            email=command.email,
            global_role=command.global_role,
            server_id=command.server_id,
            server_role=command.server_role,
            max_uses=command.max_uses,
            expires_at=expires_at,
        )

        async with UnitOfWork(self._event_bus) as uow:
            user_repo = SQLUserRepository(uow.session)
            creator = await user_repo.get(UserId(command.creator_id)) if command.creator_id else None
            if creator is None:
                raise PermissionDenied("Invalid or missing invitation creator")

            creator_role_names = {r.name for r in creator.roles}
            is_owner = "owner" in creator_role_names or any(r.has_permission("global", "*") for r in creator.roles)
            is_global_admin = (
                is_owner
                or "admin" in creator_role_names
                or any(r.has_permission("admin", "full") for r in creator.roles)
            )

            target_global = (command.global_role or "member").lower()
            if target_global == "owner" and not is_owner:
                raise PermissionDenied("Cannot create invitation with global_role 'owner' without owner privileges")
            if target_global == "admin" and not is_global_admin:
                raise PermissionDenied("Cannot create invitation with global_role 'admin' without admin privileges")

            if command.server_id:
                server_repo = SQLServerRepository(uow.session)
                server = await server_repo.get(command.server_id)
                if server is None:
                    raise InvalidValueError("server_id", command.server_id, "Server not found")

                has_server_admin = is_global_admin or (server.owner_id == str(creator.user_id))
                has_server_dev = False

                if not has_server_admin:
                    membership_repo = SQLServerMembershipRepository(uow.session)
                    membership = await membership_repo.get_membership(command.server_id, str(creator.user_id))
                    if membership:
                        if membership.role == "admin":
                            has_server_admin = True
                        elif membership.role == "dev":
                            has_server_dev = True

                target_server_role = (command.server_role or "viewer").lower()
                if target_server_role == "admin" and not has_server_admin:
                    raise PermissionDenied("Cannot grant server_role 'admin' without server admin privileges")
                if target_server_role == "dev" and not (has_server_admin or has_server_dev):
                    raise PermissionDenied("Cannot grant server_role 'dev' without server dev/admin privileges")
                if target_server_role == "viewer" and not (has_server_admin or has_server_dev):
                    raise PermissionDenied("Cannot grant server_role 'viewer' without server access")

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
                "global_role": command.global_role,
                "server_id": command.server_id,
                "server_role": command.server_role,
                "status": invitation.status.value,
                "max_uses": invitation.max_uses,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )
