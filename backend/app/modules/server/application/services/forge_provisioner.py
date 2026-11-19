from __future__ import annotations

import asyncio
import contextlib
import logging

from app.core.event_bus import EventBus
from app.modules.server.application.services.installer_provisioner import (
    INSTALL_TIMEOUT_SECONDS,
    MIN_FREE_DISK_MB,
    InstallerProvisioner,
    ProvisioningRegistry,
)
from app.modules.server.application.services.jar_service import (
    forge_installer_url,
    resolve_forge_build,
    validate_forge_supported_version,
)
from app.modules.server.domain.installer import InstallerRunner
from app.modules.server.infrastructure.fs import FileSystem

logger = logging.getLogger(__name__)

# The event loop keeps only weak references to tasks; without a strong handle a
# background install task can be garbage-collected mid-flight (between awaits).
# A done-callback both drops the reference and retrieves the exception so
# provisioning failures surface only through the persisted state and logs.
_background_tasks: set[asyncio.Task[None]] = set()


def _track_background_task(task: asyncio.Task[None]) -> None:
    _background_tasks.add(task)

    def _done(done: asyncio.Task[None]) -> None:
        _background_tasks.discard(done)
        with contextlib.suppress(asyncio.CancelledError, Exception):
            done.exception()

    task.add_done_callback(_done)


def provision_forge_server(
    server_id: str,
    minecraft_version: str,
    event_bus: EventBus | None = None,
) -> asyncio.Task[None]:
    """Spawn the Forge auto-install step off the create-request path."""
    provisioner = ForgeProvisioner(event_bus=event_bus)
    task = asyncio.create_task(provisioner.provision(server_id, minecraft_version))
    ProvisioningRegistry.register_task(str(server_id), task)
    _track_background_task(task)
    return task


class ForgeProvisioner(InstallerProvisioner):
    """Runs the Forge ``--installServer`` flow for a modern (>= 1.17) server."""

    def __init__(
        self,
        runner: InstallerRunner | None = None,
        fs: FileSystem | None = None,
        event_bus: EventBus | None = None,
        *,
        install_timeout: float = INSTALL_TIMEOUT_SECONDS,
        min_free_disk_mb: int = MIN_FREE_DISK_MB,
    ) -> None:
        super().__init__(
            runner=runner,
            fs=fs,
            event_bus=event_bus,
            install_timeout=install_timeout,
            min_free_disk_mb=min_free_disk_mb,
        )

    @property
    def provider_name(self) -> str:
        return "Forge"

    async def provision(self, server_id: str, minecraft_version: str) -> None:
        validate_forge_supported_version(minecraft_version)
        await super().provision(server_id, minecraft_version)

    async def _resolve_build(self, minecraft_version: str) -> str | None:
        validate_forge_supported_version(minecraft_version)
        return await resolve_forge_build(minecraft_version)

    def _installer_url(self, full_version: str) -> str:
        return forge_installer_url(full_version)

    def _installer_filename(self) -> str:
        return "forge-installer.jar"

    def _installer_args(self) -> str:
        return "java -jar forge-installer.jar --installServer"

    def _unix_args_relpath(self, minecraft_version: str, full_version: str) -> str:
        del minecraft_version
        return f"libraries/net/minecraftforge/forge/{full_version}/unix_args.txt"
