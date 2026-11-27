from __future__ import annotations

from pydantic import Field
from sqlalchemy import update

from app.core.authorization import resolve_primary_role
from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.auth.application.access_policy import (
    apply_user_access_policy,
    build_user_profile_dict,
)
from app.modules.auth.infrastructure.models import ApiKeyModel
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import UserId

_ROLE_RANK: dict[str, int] = {
    "viewer": 1,
    "server_admin": 2,
    "admin": 3,
    "owner": 4,
}


class UpdateUserAccessCommand(Command):
    user_id: str
    role: str
    server_ids: list[str] = Field(default_factory=list)
    all_servers_access: bool = False
    denied_permissions: list[str] = Field(default_factory=list)
    is_active: bool | None = None
    requester_id: str | None = None
    requester_roles: list[str] | None = None


class UpdateUserAccessHandler(CommandHandler[UpdateUserAccessCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: UpdateUserAccessCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLUserRepository(uow.session)
            user = await repo.get(UserId(command.user_id))
            prev_role = resolve_primary_role([r.name for r in user.roles])

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

            new_role = resolve_primary_role([r.name for r in user.roles])
            demoted = _ROLE_RANK.get(new_role, 0) < _ROLE_RANK.get(prev_role, 0)

            if command.is_active is not None:
                if command.is_active:
                    user.activate()
                else:
                    if any(r.name.lower() == "owner" for r in user.roles):
                        from app.core.exceptions import ConflictError

                        all_users = await repo.list()
                        other_owners = [
                            u
                            for u in all_users
                            if str(u.user_id) != str(user.user_id)
                            and u.is_active
                            and any(r.name.lower() == "owner" for r in u.roles)
                        ]
                        if not other_owners:
                            raise ConflictError(
                                "Cannot deactivate the last active instance owner"
                            )
                    user.deactivate()
                await repo.save(user)

            if demoted or command.is_active is False:
                for api_key in user.api_keys:
                    if not api_key.is_revoked:
                        api_key.revoke(str(user.user_id))
                await repo.save(user)
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

            profile = await build_user_profile_dict(uow.session, str(user.user_id))

        from app.websocket.endpoint import disconnect_user_sessions, revalidate_user_sessions

        if command.is_active is False:
            await disconnect_user_sessions(str(user.user_id), reason="Account deactivated")
        else:
            await revalidate_user_sessions(str(user.user_id))

        return CommandResult(success=True, data=profile or {})
