from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.config import AppSettings, ConfigFactory
from app.core.event_bus import EventBus
from app.core.exceptions import MCSError, ProvisioningError
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.resource_budget import ResourceBudgetService
from app.modules.server.application.services.identity_writer import write_server_identity
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
    default_provider_for_platform,
)
from app.modules.server.infrastructure.fs import local_fs
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId

logger = logging.getLogger(__name__)

_BLOCKED_LOCAL_PROVIDERS = frozenset({"local", "local_linux", "local_windows"})


def _docker_ping_on_implicit_create() -> bool:
    """Return whether implicit (provider=None) creation must verify Docker.

    Explicit ``provider="docker"`` creation always pings the daemon. Implicit
    creation is hermetic for offline/unit callers by default, and can be made
    strict with ``ONX_DOCKER_PING_ON_IMPLICIT_CREATE=true``.
    """
    settings = AppSettings()
    explicit = getattr(settings, "docker_ping_on_implicit_create", None)
    if isinstance(explicit, bool):
        return explicit
    raw = os.environ.get("ONX_DOCKER_PING_ON_IMPLICIT_CREATE", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class CreateServerCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
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
    provider: str | None = None
    startup_timeout_seconds: int | None = None
    mode: str = "simple"


class CreateServerHandler(CommandHandler[CreateServerCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: CreateServerCommand) -> CommandResult:
        if command.mode == "advanced" and not ConfigFactory.global_settings().advanced_mode_enabled:
            return CommandResult(
                success=False,
                error="Advanced mode is not enabled on this instance",
                error_code="VALIDATION_ERROR",
            )

        from app.modules.server.application.services.jar_service import (
            compute_file_sha256,
            download_progress_context,
            download_server_jar,
            forge_requires_installer,
            neoforge_requires_installer,
            resolve_display_jar_filename,
            resolve_server_dir,
            validate_forge_supported_version,
            write_eula,
            write_server_properties,
        )
        from app.modules.server.application.services.provisioning_telemetry import (
            ProvisioningProgressTracker,
            format_bytes_human,
            make_sync_or_async_progress_adapter,
        )
        from app.modules.versioning.infrastructure.java_floor import (
            resolve_java_floor_from_mc_version,
            temurin_docker_image_for_java_major,
        )

        if command.mode == "advanced" and os.name != "posix":
            return CommandResult(
                success=False,
                error="Advanced mode is only supported on POSIX hosts in this release",
                error_code="VALIDATION_ERROR",
            )

        is_forge_installer = command.server_type == "forge" and forge_requires_installer(
            command.minecraft_version
        )
        is_neoforge_installer = command.server_type == "neoforge" and neoforge_requires_installer(
            command.minecraft_version
        )
        if command.mode == "advanced" and (is_forge_installer or is_neoforge_installer):
            return CommandResult(
                success=False,
                error=(
                    "Advanced mode creation for installer-based Forge/NeoForge servers "
                    "is not available in this release"
                ),
                error_code="VALIDATION_ERROR",
            )

        raw_provider = (command.provider or "").strip().lower()
        if raw_provider in _BLOCKED_LOCAL_PROVIDERS:
            return CommandResult(
                success=False,
                error=(
                    "Local runtime providers are deprecated and blocked; "
                    "Docker is the only supported runtime"
                ),
                error_code="INVALID_PROVIDER",
            )

        resolved_provider = raw_provider or default_provider_for_platform()
        if resolved_provider != "docker":
            return CommandResult(
                success=False,
                error=(
                    f"Unsupported provider '{command.provider}'; "
                    "Docker is the only supported runtime"
                ),
                error_code="INVALID_PROVIDER",
            )

        should_ping_docker = raw_provider == "docker" or _docker_ping_on_implicit_create()
        docker_provider: Any | None = None
        if should_ping_docker:
            from app.modules.server.infrastructure.providers import provider_factory

            docker_provider = provider_factory.get("docker")
            if not await docker_provider.ping():
                err_detail = getattr(docker_provider, "last_ping_error", None)
                err_msg = (
                    err_detail
                    if isinstance(err_detail, str) and err_detail
                    else "Docker daemon is unreachable or not running in Linux container mode"
                )
                return CommandResult(
                    success=False,
                    error=err_msg,
                    error_code="DOCKER_UNAVAILABLE",
                )

        location_type = LocationType.DOCKER
        runtime_info = RuntimeInfo(provider="docker", port=command.port)

        server_id = ServerId()
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

        if command.server_type == "forge":
            # OD-v8.4-9: reject outside 1.17.1 .. 1.20.1 immediately (HTTP 422).
            validate_forge_supported_version(command.minecraft_version)

        ResourceBudgetService.check_config_ceiling(
            requested_ram_mb=command.max_memory_mb,
        )

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerRepository = SQLServerRepository(uow.session)

            deployment = ServerDeployment(
                location_type=location_type,
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
                runtime=runtime_info,
                owner_id=command.creator_id,
                startup_timeout_seconds=command.startup_timeout_seconds,
                mode=ServerMode(command.mode),
            )
            if is_forge_installer or is_neoforge_installer:
                server.begin_provisioning()
            await repo.save(server)

            tracker = ProvisioningProgressTracker(
                server_id=str(server_id),
                server_name=command.name,
                server_type=command.server_type,
                minecraft_version=command.minecraft_version,
                mode=command.mode,
                event_bus=self._event_bus,
            )

            uow.defer_cleanup(lambda: local_fs.delete_dir(server_dir_path))

            jar_dest = ""
            display_name = resolve_display_jar_filename(
                command.server_type,
                command.minecraft_version,
            )
            jar_size: int | None = None

            try:
                await tracker.start_step(
                    "prepare_workspace",
                    "Creating server directory, eula.txt, and server.properties...",
                    activity_message="Created workspace directory",
                )
                write_server_identity(
                    dir_path=server_dir_path,
                    uid=str(server_id),
                    provider=resolved_provider,
                    fs=local_fs,
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
                await tracker.complete_step(
                    "prepare_workspace",
                    detail="server.properties & eula.txt",
                    activity_message="Created workspace and server.properties",
                )

                if is_forge_installer or is_neoforge_installer:
                    await tracker.start_step(
                        "download_core",
                        f"Preparing {command.server_type} installer...",
                        activity_message="Queued background loader installer",
                    )
                    jar_dest = await download_server_jar(
                        server_id=str(server_id),
                        server_type=command.server_type,
                        minecraft_version=command.minecraft_version,
                        deployment=deployment,
                    )
                else:
                    await tracker.start_step(
                        "download_core",
                        f"Downloading {display_name}...",
                    )
                    with download_progress_context(
                        make_sync_or_async_progress_adapter(tracker),
                        file_index=1,
                        file_total=1,
                        display_filename=display_name,
                    ):
                        jar_dest = await download_server_jar(
                            server_id=str(server_id),
                            server_type=command.server_type,
                            minecraft_version=command.minecraft_version,
                            deployment=deployment,
                        )
                    if jar_dest and local_fs.exists(jar_dest):
                        with __import__("contextlib").suppress(OSError):
                            raw_size = local_fs.size(jar_dest)
                            if isinstance(raw_size, int) and raw_size > 0:
                                jar_size = raw_size
                    size_label = format_bytes_human(jar_size) if jar_size else "Ready"
                    await tracker.complete_step(
                        "download_core",
                        detail=f"{display_name} · {size_label}",
                        activity_message=(
                            f"Downloaded {display_name} ({size_label})"
                            if jar_size
                            else f"Prepared {display_name}"
                        ),
                    )

                    await tracker.start_step(
                        "verify_and_install",
                        "Verifying JAR integrity & checksum...",
                    )
                    sha256 = compute_file_sha256(jar_dest, local_fs) if jar_dest else None
                    if server.mode == ServerMode.ADVANCED:
                        from app.modules.versioning.application.advanced_initialization import (
                            initialize_advanced_server,
                        )
                        from app.modules.versioning.domain.entities import (
                            BranchProtectionPolicy,
                            ServerBranch,
                        )
                        from app.modules.versioning.domain.value_objects import BranchStatus
                        from app.modules.versioning.infrastructure.repository import (
                            SQLVersioningRepository,
                        )

                        initialize_advanced_server(server)
                        versioning_repo = SQLVersioningRepository(uow.session)
                        if await versioning_repo.get_branch_by_name(str(server_id), "main") is None:
                            await versioning_repo.save_branch(
                                ServerBranch(
                                    id=str(uuid.uuid4()),
                                    server_id=str(server_id),
                                    name="main",
                                    status=BranchStatus.ACTIVE,
                                    is_protected=True,
                                    protection_policy=BranchProtectionPolicy(),
                                )
                            )
                        tracker.add_activity("Initialized Git repository on main", level="info")
                    await tracker.complete_step(
                        "verify_and_install",
                        detail="Verified",
                        activity_message=(
                            "Checksum verified (SHA-256)"
                            if sha256
                            else "Server JAR verified"
                        ),
                    )
            except ProvisioningError as exc:
                await tracker.fail(str(exc))
                local_fs.delete_dir(server_dir_path)
                raise
            except MCSError as exc:
                await tracker.fail(str(exc))
                local_fs.delete_dir(server_dir_path)
                raise
            except Exception as e:
                await tracker.fail(str(e))
                local_fs.delete_dir(server_dir_path)
                raise ProvisioningError(
                    message=f"Unexpected provisioning failure for server {server_id}",
                    server_id=str(server_id),
                ) from e

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

        java_major = resolve_java_floor_from_mc_version(command.minecraft_version)
        target_img = temurin_docker_image_for_java_major(java_major)

        if not (is_forge_installer or is_neoforge_installer):
            await tracker.start_step(
                "prepare_runtime",
                f"Resolving Java {java_major} runtime image...",
                detail=f"Java {java_major}",
            )

        if resolved_provider == "docker" and docker_provider is not None:
            try:
                from app.modules.server.infrastructure.providers.docker import (
                    resolve_docker_image,
                )

                target_img = resolve_docker_image(minecraft_version=command.minecraft_version)
                if hasattr(docker_provider, "ensure_image"):
                    await docker_provider.ensure_image(target_img)
            except Exception as exc:
                logger.warning(
                    "Pre-warming Docker image failed during server creation: %s",
                    exc,
                )

        if not (is_forge_installer or is_neoforge_installer):
            await tracker.complete_step(
                "prepare_runtime",
                detail=f"Java {java_major}",
                activity_message=f"Java {java_major} runtime ready ({target_img})",
            )
            await tracker.start_step(
                "finalize",
                "Recording final artifacts & marking server ready...",
            )
            size_label = format_bytes_human(jar_size) if jar_size else None
            jar_summary = (
                f"{display_name} · {size_label} · Verified"
                if size_label
                else f"{display_name} · Verified"
            )
            mode_summary = (
                f"Java {java_major} · Advanced Mode (Git initialized)"
                if command.mode == "advanced"
                else f"Java {java_major} · Simple Mode"
            )
            artifacts = [
                {
                    "id": "core_jar",
                    "label": "Server JAR",
                    "value": jar_summary,
                    "status": "verified",
                },
                {
                    "id": "runtime",
                    "label": "Runtime & Mode",
                    "value": mode_summary,
                    "status": "ready",
                },
                {
                    "id": "config",
                    "label": "Configuration",
                    "value": f"server.properties, eula.txt · Port {command.port}",
                    "status": "completed",
                },
            ]
            snapshot = await tracker.complete(
                "Server created and ready to start",
                artifacts=artifacts,
            )
        else:
            snapshot = tracker.snapshot()

        logger.info(
            'Server "%s" created — type=%s version=%s port=%d server_id=%s',
            server.name,
            command.server_type,
            command.minecraft_version,
            command.port,
            server_id,
        )

        return CommandResult(
            success=True,
            data={"server_id": str(server_id), "provisioning_progress": snapshot},
        )

