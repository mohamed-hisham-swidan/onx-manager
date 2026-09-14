from __future__ import annotations

import contextlib
import logging
import os

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ServerNotFoundError
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.plugin.domain.repository import PluginRepository
from app.modules.plugin.infrastructure.addon_fs import (
    get_addon_dir_name,
    toggle_addon_file,
)
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.fs import FileSystem, local_fs
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import PluginId, ServerId

logger = logging.getLogger(__name__)


class ToggleModStateCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    mod_id: str | None = None
    plugin_id: str | None = None
    enabled: bool


class ToggleModStateHandler(CommandHandler[ToggleModStateCommand]):
    def __init__(self, event_bus: EventBus, fs: FileSystem | None = None) -> None:
        self._event_bus = event_bus
        self._fs = fs or local_fs

    async def handle(self, command: ToggleModStateCommand) -> CommandResult:
        server_id = ServerId(command.server_id)

        async with UnitOfWork(self._event_bus) as uow:
            repo: PluginRepository = SQLPluginRepository(uow.session)
            server_repo: ServerRepository = SQLServerRepository(uow.session)

            plugin = None
            if command.plugin_id:
                try:
                    plugin = await repo.get(PluginId(command.plugin_id))
                except Exception:
                    plugin = None

            if plugin is None and command.mod_id:
                all_plugins = await repo.list_all_by_server(server_id)
                for p in all_plugins:
                    if (
                        p.mod_id == command.mod_id
                        or str(p.plugin_id) == command.mod_id
                        or p.name == command.mod_id
                        or p.filename == command.mod_id
                    ):
                        plugin = p
                        break

            if plugin is None:
                return CommandResult(
                    success=False,
                    error="Mod/plugin not found on this server.",
                    error_code="PLUGIN_NOT_FOUND",
                )

            server = None
            with contextlib.suppress(ServerNotFoundError):
                server = await server_repo.get(server_id)

            if server and server.deployment and server.deployment.root_path and plugin.filename:
                server_type = server.server_type.value
                addon_dir_name = get_addon_dir_name(server_type)
                server_dir = server.deployment.server_directory()

                # Check both primary addon dir and fallback plugins dir
                dirs_to_check = [
                    os.path.join(server_dir, addon_dir_name),
                    os.path.join(server_dir, "plugins"),
                    os.path.join(server_dir, "mods"),
                ]
                renamed_ok = False
                for d in dict.fromkeys(dirs_to_check):
                    if self._fs.exists(d):
                        try:
                            toggle_addon_file(d, plugin.filename, command.enabled)
                            renamed_ok = True
                            break
                        except FileNotFoundError:
                            continue
                        except OSError as exc:
                            return CommandResult(
                                success=False,
                                error=f"Physical file rename failed: {exc}",
                                error_code="FS_ERROR",
                            )

                if not renamed_ok:
                    logger.warning(
                        "Addon file '%s' was not found on disk during toggle on server %s",
                        plugin.filename,
                        server_id,
                    )

            plugin.set_disabled_on_disk(not command.enabled)
            if command.enabled:
                plugin.enable()
            else:
                plugin.disable()

            await repo.save(plugin)
            for event in plugin.collect_events():
                uow.add_event(event)
            await uow.commit()

        data: dict = {
            "plugin_id": str(plugin.plugin_id),
            "server_id": str(server_id),
            "name": plugin.name,
            "enabled": command.enabled,
            "status": plugin.status.value,
            "is_disabled_on_disk": plugin.is_disabled_on_disk,
        }
        return CommandResult(success=True, data=data)
