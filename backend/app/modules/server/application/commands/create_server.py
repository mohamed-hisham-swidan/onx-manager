from __future__ import annotations

import logging
from pathlib import Path

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ProvisioningError
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.fs import local_fs
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId

logger = logging.getLogger(__name__)


class CreateServerCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    creator_id: str | None = None
    name: str
    server_type: str = "vanilla"
    minecraft_version: str
    min_memory_mb: int = 1024
    max_memory_mb: int = 2048
    port: int = 25565
    motd: str = "A Minecraft Server"
    max_players: int = 20
    gamemode: str = "survival"
    difficulty: str = "easy"
    spawn_protection: int = 16
    pvp: bool = True
    enable_command_block: bool = False
    online_mode: bool = True
    whitelist: bool = False
    view_distance: int = 10
    simulation_distance: int = 10
    java_args: list[str] | None = None
    group_id: str = "default"
    install_dir: str | None = None


class CreateServerHandler(CommandHandler[CreateServerCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: CreateServerCommand) -> CommandResult:
        from app.modules.server.application.services.jar_service import (
            download_server_jar,
            forge_requires_installer,
            neoforge_requires_installer,
            resolve_server_dir,
            write_eula,
            write_server_properties,
        )

        server_id = ServerId()
        is_forge_installer = command.server_type == "forge" and forge_requires_installer(
            command.minecraft_version
        )
        is_neoforge_installer = command.server_type == "neoforge" and neoforge_requires_installer(
            command.minecraft_version
        )
        server_dir_path = resolve_server_dir(
            server_id=str(server_id),
            name=command.name,
        )

        try:
            parsed_version = MinecraftVersion.parse(command.minecraft_version)
        except ValueError as exc:
            return CommandResult(
                success=False,
                error=str(exc),
                error_code="VALIDATION_ERROR",
            )

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerRepository = SQLServerRepository(uow.session)

            deployment = ServerDeployment(
                location_type=LocationType.LOCAL,
                root_path=str(Path(server_dir_path).resolve()),
                working_directory=".",
                startup_jar="server.jar",
            )

            server = Server.create(
                server_id=server_id,
                name=command.name,
                server_type=ServerType(command.server_type),
                minecraft_version=parsed_version,
                memory=MemoryAllocation(
                    min_mb=command.min_memory_mb,
                    max_mb=command.max_memory_mb,
                ),
                java_args=JavaArguments(command.java_args),
                properties=ServerProperties(
                    port=PortNumber(command.port),
                    motd=command.motd,
                    max_players=command.max_players,
                    gamemode=command.gamemode,
                    difficulty=command.difficulty,
                    spawn_protection=command.spawn_protection,
                    pvp=command.pvp,
                    enable_command_block=command.enable_command_block,
                    online_mode=command.online_mode,
                    whitelist=command.whitelist,
                    view_distance=command.view_distance,
                    simulation_distance=command.simulation_distance,
                ),
                group_id=command.group_id,
                deployment=deployment,
                owner_id=command.creator_id,
            )
            if is_forge_installer or is_neoforge_installer:
                server.begin_provisioning()
            await repo.save(server)

            uow.defer_cleanup(lambda: local_fs.delete_dir(server_dir_path))

            try:
                await download_server_jar(
                    server_id=str(server_id),
                    server_type=command.server_type,
                    minecraft_version=command.minecraft_version,
                    deployment=deployment,
                )
                write_eula(str(server_id), deployment=deployment)
                write_server_properties(
                    str(server_id),
                    {
                        "name": command.name,
                        "port": command.port,
                        "motd": command.motd,
                        "max_players": command.max_players,
                        "gamemode": command.gamemode,
                        "difficulty": command.difficulty,
                        "spawn_protection": command.spawn_protection,
                        "pvp": command.pvp,
                        "enable_command_block": command.enable_command_block,
                        "online_mode": command.online_mode,
                        "whitelist": command.whitelist,
                        "view_distance": command.view_distance,
                        "simulation_distance": command.simulation_distance,
                    },
                    deployment=deployment,
                )
            except ProvisioningError:
                local_fs.delete_dir(server_dir_path)
                raise
            except Exception:
                local_fs.delete_dir(server_dir_path)
                raise ProvisioningError(
                    message=f"Unexpected provisioning failure for server {server_id}",
                    server_id=str(server_id),
                ) from None

            for event in server.collect_events():
                uow.add_event(event)
            await uow.commit()

        if is_forge_installer:
            from app.modules.server.application.services.forge_provisioner import (
                provision_forge_server,
            )

            provision_forge_server(
                server_id=str(server_id),
                minecraft_version=command.minecraft_version,
                event_bus=self._event_bus,
            )

        if is_neoforge_installer:
            from app.modules.server.application.services.neoforge_provisioner import (
                provision_neoforge_server,
            )

            provision_neoforge_server(
                server_id=str(server_id),
                minecraft_version=command.minecraft_version,
                event_bus=self._event_bus,
            )

        logger.info(
            'Server "%s" created — type=%s version=%s port=%d server_id=%s',
            server.name,
            command.server_type,
            command.minecraft_version,
            command.port,
            server_id,
        )

        return CommandResult(success=True, data={"server_id": str(server_id)})
