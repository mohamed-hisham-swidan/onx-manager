import logging
import tempfile
from pathlib import Path

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.identity import IDENTITY
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.server.application.services.identity_writer import write_server_identity
from app.modules.server.application.services.import_service import (
    _find_server_jar,
    _safe_extract_zip,
    get_effective_server_dir,
)
from app.modules.server.application.services.jar_service import resolve_server_dir
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    RuntimeInfo,
    ServerDeployment,
    ServerMode,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.fs import local_fs
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.commands.import_server")

SERVERS_DATA_DIR: str = ""  # kept for backward compat with migrate_import_arch.py imports

_BLOCKED_LOCAL_PROVIDERS = frozenset({"local", "local_linux", "local_windows"})


class ImportServerCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    creator_id: str | None = None
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
    mode: str = "simple"
    provider: str | None = None


class ImportServerHandler(CommandHandler[ImportServerCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: ImportServerCommand) -> CommandResult:
        if command.mode == "advanced":
            return CommandResult(
                success=False,
                error="Advanced mode imports are not supported in this release",
                error_code="CONFLICT",
                details={"mode": "advanced"},
            )

        raw_provider = (command.provider or "").strip().lower()
        if raw_provider in _BLOCKED_LOCAL_PROVIDERS or (
            raw_provider and raw_provider != "docker"
        ):
            return CommandResult(
                success=False,
                error=(
                    "Local runtime providers are deprecated and blocked; "
                    "Docker is the only supported runtime"
                ),
                error_code="INVALID_PROVIDER",
            )

        source = Path(command.source_path).expanduser().resolve()
        is_zip = source.is_file() and source.name.lower().endswith(".zip")
        if not source.is_dir() and not is_zip:
            return CommandResult(
                success=False,
                error=f"Directory or zip archive not found: {command.source_path}",
            )

        def _cleanup_staging() -> None:
            try:
                from app.core.config import AppSettings

                staging_root = Path(AppSettings().import_staging_dir).resolve()
                if source.is_relative_to(staging_root):
                    rel_parts = source.relative_to(staging_root).parts
                    if rel_parts:
                        import_dir = staging_root / rel_parts[0]
                        local_fs.delete_dir(str(import_dir))
            except Exception as cleanup_err:
                logger.warning(
                    "Failed to clean up staging directory for %s: %s",
                    source,
                    cleanup_err,
                )

        try:
            server_id = ServerId()
            target = Path(resolve_server_dir(str(server_id), name=command.name)).resolve()

            if target.exists():
                return CommandResult(
                    success=False,
                    error=f"Target directory already exists: {target}",
                )

            async with UnitOfWork(self._event_bus) as uow:
                try:
                    if is_zip:
                        with tempfile.TemporaryDirectory() as td:
                            temp_extracted = Path(td) / "extracted"
                            temp_extracted.mkdir(parents=True, exist_ok=True)
                            _safe_extract_zip(source, temp_extracted)
                            effective = get_effective_server_dir(temp_extracted)
                            local_fs.copy_dir(str(effective), str(target))
                    else:
                        local_fs.copy_dir(str(source), str(target))
                except Exception as exc:
                    logger.error("Failed to copy server directory: %s", exc)
                    return CommandResult(
                        success=False,
                        error=f"Failed to copy server directory: {exc}",
                    )

                uow.defer_cleanup(lambda p=str(target): local_fs.delete_dir(p))

                # Remove any stale legacy identity folder copied from source archive
                legacy_identity_dir = target / IDENTITY.identity_dir_legacy
                if legacy_identity_dir.exists():
                    local_fs.delete_dir(str(legacy_identity_dir))

                # Authoritatively stamp new server identity
                provider_type = "docker"
                write_server_identity(
                    dir_path=str(target),
                    uid=str(server_id),
                    provider=provider_type,
                    fs=local_fs,
                )

                detected_jar = _find_server_jar(str(target), local_fs) or "server.jar"

                deployment = ServerDeployment(
                    location_type=LocationType.DOCKER,
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
                    runtime=RuntimeInfo(provider="docker", port=command.port),
                    owner_id=command.creator_id,
                    mode=ServerMode(command.mode),
                )
                await repo.save(server)

                for event in server.collect_events():
                    uow.add_event(event)
                await uow.commit()

            logger.info(
                'Server "%s" imported from %s → %s (jar=%s server_id=%s)',
                command.name,
                source,
                target,
                detected_jar,
                server_id,
            )

            return CommandResult(success=True, data={"server_id": str(server_id)})
        finally:
            _cleanup_staging()
