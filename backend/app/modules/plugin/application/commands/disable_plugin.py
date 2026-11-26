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
from app.modules.shared.value_objects import PluginId

logger = logging.getLogger(__name__)


class DisablePluginCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    plugin_id: str


class DisablePluginHandler(CommandHandler[DisablePluginCommand]):
    def __init__(self, event_bus: EventBus, fs: FileSystem | None = None) -> None:
        self._event_bus = event_bus
        self._fs = fs or local_fs

    async def handle(self, command: DisablePluginCommand) -> CommandResult:
        plugin_id = PluginId(command.plugin_id)

        async with UnitOfWork(self._event_bus) as uow:
            repo: PluginRepository = SQLPluginRepository(uow.session)
            server_repo: ServerRepository = SQLServerRepository(uow.session)
            plugin = await repo.get(plugin_id)

            server = None
            with contextlib.suppress(ServerNotFoundError):
                server = await server_repo.get(plugin.server_id)

            if server and server.deployment and server.deployment.root_path and plugin.filename:
                server_type = server.server_type.value
                addon_dir_name = get_addon_dir_name(server_type)
                server_dir = server.deployment.server_directory()

                dirs_to_check = [
                    os.path.join(server_dir, addon_dir_name),
                    os.path.join(server_dir, "plugins"),
                    os.path.join(server_dir, "mods"),
                ]
                any_dir_exists = False
                renamed_ok = False
                for d in dict.fromkeys(dirs_to_check):
                    if self._fs.exists(d):
                        any_dir_exists = True
                        try:
                            toggle_addon_file(d, plugin.filename, enabled=False)
                            renamed_ok = True
                            break
                        except FileNotFoundError:
                            continue
                        except OSError as exc:
                            logger.error(
                                "Failed to rename addon file on disable: %s (%s)",
                                plugin.filename,
                                exc,
                            )
                            return CommandResult(
                                success=False,
                                error=f"Physical file rename failed: {exc}",
                                error_code="FS_ERROR",
                            )
                if any_dir_exists and not renamed_ok:
                    return CommandResult(
                        success=False,
                        error=f"Addon file '{plugin.filename}' was not found on disk.",
                        error_code="FILE_NOT_FOUND",
                    )

            plugin.set_disabled_on_disk(True)
            plugin.disable()
            await repo.save(plugin)
            for event in plugin.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(
            success=True,
            data={"plugin_id": command.plugin_id, "is_disabled_on_disk": True},
        )
