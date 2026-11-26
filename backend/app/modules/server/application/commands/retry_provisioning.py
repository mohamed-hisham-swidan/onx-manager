from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ServerNotFoundError
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.server.domain.aggregate import ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryProvisioningCommand(Command):
    server_id: str


class RetryProvisioningHandler(CommandHandler[RetryProvisioningCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: RetryProvisioningCommand) -> CommandResult:
        sid = ServerId(command.server_id)
        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerRepository = SQLServerRepository(uow.session)
            try:
                server = await repo.get(sid)
            except ServerNotFoundError:
                return CommandResult(
                    success=False,
                    error=f"Server {command.server_id} not found",
                    error_code="SERVER_NOT_FOUND",
                )
            if not server:
                return CommandResult(
                    success=False,
                    error=f"Server {command.server_id} not found",
                    error_code="SERVER_NOT_FOUND",
                )
            if server.status != ServerStatus.PROVISIONING_FAILED:
                return CommandResult(
                    success=False,
                    error=(
                        f"Server {command.server_id} is in status '{server.status.value}', "
                        f"expected '{ServerStatus.PROVISIONING_FAILED.value}'"
                    ),
                    error_code="INVALID_STATUS",
                )
            server.begin_provisioning()
            await repo.save(server)
            for event in server.collect_events():
                uow.add_event(event)
            await uow.commit()

        stype = server.server_type.value
        mv = server.minecraft_version
        if mv.patch == 0 and (mv.major >= 26 or (mv.major == 1 and mv.minor in (19, 20, 21))):
            mc_ver = f"{mv.major}.{mv.minor}"
        else:
            mc_ver = str(mv)

        from app.modules.server.application.services.provisioning_telemetry import (
            ProvisioningProgressTracker,
        )

        tracker = ProvisioningProgressTracker(
            server_id=str(sid),
            server_name=server.name,
            server_type=stype,
            minecraft_version=mc_ver,
            mode=server.mode.value,
            event_bus=self._event_bus,
        )
        await tracker.complete_step(
            "prepare_workspace",
            detail="Workspace ready",
            activity_message="Retrying server installation",
        )
        await tracker.start_step(
            "download_core",
            f"Preparing {stype} installer...",
        )

        if stype == "forge":
            from app.modules.server.application.services.forge_provisioner import (
                provision_forge_server,
            )

            provision_forge_server(
                server_id=str(sid),
                minecraft_version=mc_ver,
                event_bus=self._event_bus,
            )
        elif stype == "neoforge":
            from app.modules.server.application.services.neoforge_provisioner import (
                provision_neoforge_server,
            )

            provision_neoforge_server(
                server_id=str(sid),
                minecraft_version=mc_ver,
                event_bus=self._event_bus,
            )
        else:
            return CommandResult(
                success=False,
                error=(
                    f"Server {command.server_id} with type '{stype}' "
                    "does not use installer provisioning"
                ),
                error_code="UNSUPPORTED_SERVER_TYPE",
            )

        return CommandResult(
            success=True,
            data={"server_id": str(sid), "status": ServerStatus.PROVISIONING.value},
        )
