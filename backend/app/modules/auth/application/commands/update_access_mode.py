from __future__ import annotations

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import InvalidValueError, PermissionDenied
from app.core.local_auth import require_password_configured_for_exposure
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.version import get_app_version
from app.modules.auth.domain.aggregate import AccessMode
from app.modules.auth.infrastructure.repository import SQLSystemStateRepository, SQLUserRepository


class UpdateAccessModeCommand(Command):
    access_mode: str
    requester_roles: list[str] = []
    requester_permissions: list[str] = []


class UpdateAccessModeHandler(CommandHandler[UpdateAccessModeCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: UpdateAccessModeCommand) -> CommandResult:
        # Enforce Owner-only authorization in handler
        is_owner = "owner" in command.requester_roles or "global.*" in command.requester_permissions
        if not is_owner:
            raise PermissionDenied("Only the instance Owner can change the Access Mode")

        mode_str = command.access_mode.upper()
        if mode_str not in ("LOCAL", "GLOBAL"):
            raise InvalidValueError(
                "access_mode", command.access_mode, "Access mode must be LOCAL or GLOBAL"
            )

        target_mode = AccessMode.GLOBAL if mode_str == "GLOBAL" else AccessMode.LOCAL

        async with UnitOfWork(self._event_bus) as uow:
            sys_repo = SQLSystemStateRepository(uow.session)
            state = await sys_repo.get_with_lock("default")

            if not state.initialized:
                raise InvalidValueError(
                    "access_mode", command.access_mode, "Instance is not initialized"
                )

            if target_mode == AccessMode.GLOBAL:
                await require_password_configured_for_exposure(
                    uow.session, action="access_mode_global"
                )

            state.set_access_mode(target_mode)
            await sys_repo.save(state)

            user_repo = SQLUserRepository(uow.session)
            users = await user_repo.list()
            user_count = len(users)

            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "initialized": True,
                "access_mode": target_mode.value
                if hasattr(target_mode, "value")
                else str(target_mode),
                "user_count": user_count,
                "version": get_app_version(),
                "password_configured": state.password_configured,
            },
        )
