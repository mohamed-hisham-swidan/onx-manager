from __future__ import annotations

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import UserId


class DeleteUserCommand(Command):
    user_id: str
    requester_id: str | None = None
    requester_roles: list[str] | None = None


class DeleteUserHandler(CommandHandler[DeleteUserCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: DeleteUserCommand) -> CommandResult:
        from app.core.exceptions import ConflictError, NotFoundError, PermissionDenied

        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLUserRepository(uow.session)
            try:
                user = await repo.get(UserId(command.user_id))
            except NotFoundError:
                return CommandResult(success=False, error="User not found", error_code="NOT_FOUND")
            if command.requester_roles is not None:
                requester_roles = {str(r).lower() for r in command.requester_roles}
                target_is_owner = any(r.name.lower() == "owner" for r in user.roles)
                if target_is_owner and "owner" not in requester_roles:
                    raise PermissionDenied(
                        "Only an instance Owner can delete an Owner account"
                    )
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
                    raise ConflictError("Cannot delete the last active instance owner")
            await repo.delete(UserId(command.user_id))
            for event in user.collect_events():
                uow.add_event(event)
            await uow.commit()

        from app.websocket.endpoint import disconnect_user_sessions

        await disconnect_user_sessions(command.user_id, reason="User deleted")

        return CommandResult(success=True, data={})
