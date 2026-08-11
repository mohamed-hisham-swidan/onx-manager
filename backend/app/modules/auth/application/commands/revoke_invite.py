from __future__ import annotations

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import NotFoundError
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.auth.infrastructure.repository import SQLInvitationRepository


class RevokeInviteCommand(Command):
    invitation_id: str


class RevokeInviteHandler(CommandHandler[RevokeInviteCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: RevokeInviteCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLInvitationRepository(uow.session)
            invitation = await repo.get(command.invitation_id)
            if invitation is None:
                raise NotFoundError(f"Invitation '{command.invitation_id}' not found")

            invitation.revoke()
            await repo.save(invitation)
            await uow.commit()

        return CommandResult(success=True, data={"revoked": True, "invitation_id": command.invitation_id})
