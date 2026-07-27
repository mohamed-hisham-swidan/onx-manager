import logging

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
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
from app.modules.server.application.services.import_service import _find_server_jar
from app.modules.server.application.services.jar_service import resolve_server_dir
from app.modules.shared.value_objects import MinecraftVersion, ServerId
from app.core.persistence.unit_of_work import UnitOfWork

logger = logging.getLogger("mcs.commands.import_server")

SERVERS_DATA_DIR: str = ""  # kept for backward compat with migrate_import_arch.py imports


class ImportServerCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    source_path: str
    name: str
    server_type: str = "vanilla"
    minecraft_version: str
    port: int = 25565
    max_players: int = 20
    motd: str = "A Minecraft Server"
    gamemode: str = "survival"
    difficulty: str = "easy"
    spawn_protection: int = 16
    pvp: bool = True
    enable_command_block: bool = False
    online_mode: bool = True
    whitelist: bool = False
    view_distance: int = 10
    simulation_distance: int = 10
    min_memory_mb: int = 1024
    max_memory_mb: int = 2048
    group_id: str = "default"


class ImportServerHandler(CommandHandler[ImportServerCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: ImportServerCommand) -> CommandResult:
        from pathlib import Path

        source = Path(command.source_path).expanduser().resolve()
        if not source.is_dir():
            return CommandResult(
                success=False,
                error=f"Directory not found: {command.source_path}",
            )

        server_id = ServerId()
        target = Path(resolve_server_dir(str(server_id), name=command.name)).resolve()

        if target.exists():
            return CommandResult(
                success=False,
                error=f"Target directory already exists: {target}",
            )

        async with UnitOfWork(self._event_bus) as uow:
            try:
                local_fs.copy_dir(str(source), str(target))
            except Exception as exc:
                logger.error("Failed to copy server directory: %s", exc)
                return CommandResult(
                    success=False,
                    error=f"Failed to copy server directory: {exc}",
                )

            uow.defer_cleanup(lambda p=str(target): local_fs.delete_dir(p))

            detected_jar = _find_server_jar(str(target), local_fs) or "server.jar"

            deployment = ServerDeployment(
                location_type=LocationType.LOCAL,
                location_uri=f"file://{target}",
                root_path=str(target),
                working_directory=".",
                startup_jar=detected_jar,
                primary_world="world",
            )

            repo: ServerRepository = SQLServerRepository(uow.session)

            server = Server.create(
                server_id=server_id,
                name=command.name,
                server_type=ServerType(command.server_type),
                minecraft_version=MinecraftVersion.parse(command.minecraft_version),
                memory=MemoryAllocation(
                    min_mb=command.min_memory_mb,
                    max_mb=command.max_memory_mb,
                ),
                java_args=JavaArguments([]),
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
            )
            await repo.save(server)

            for event in server.collect_events():
                uow.add_event(event)
            await uow.commit()

        logger.info(
            'Server "%s" imported from %s → %s (jar=%s server_id=%s)',
            command.name, source, target, detected_jar, server_id,
        )

        return CommandResult(success=True, data={"server_id": str(server_id)})