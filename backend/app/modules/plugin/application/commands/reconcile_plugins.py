from __future__ import annotations

import logging
import os

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.plugin.domain.aggregate import Plugin
from app.modules.plugin.domain.repository import PluginRepository
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.fs import FileSystem, local_fs
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId

logger = logging.getLogger(__name__)


class ReconcilePluginsCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str


class ReconcilePluginsHandler(CommandHandler[ReconcilePluginsCommand]):
    """Make the plugins DB table reflect the actual filesystem state.

    The filesystem (``<server_dir>/plugins/*.jar``) is the source of truth for
    which plugins exist. The DB is only a metadata cache layered on top of it.
    """

    def __init__(self, event_bus: EventBus, fs: FileSystem | None = None) -> None:
        self._event_bus = event_bus
        self._fs = fs or local_fs

    async def handle(self, command: ReconcilePluginsCommand) -> CommandResult:
        server_id = ServerId(command.server_id)

        async with UnitOfWork(self._event_bus) as uow:
            server_repo: ServerRepository = SQLServerRepository(uow.session)
            server = await server_repo.get(server_id)

            if server.deployment is None or not server.deployment.root_path:
                logger.info(
                    "Plugin reconciliation skipped — no deployment root for server_id=%s",
                    str(server_id),
                )
                return CommandResult(
                    success=True,
                    data={"server_id": str(server_id), "added": [], "removed": []},
                )

            plugin_dir = os.path.join(server.deployment.server_directory(), "plugins")
            repo: PluginRepository = SQLPluginRepository(uow.session)

            disk_files = {
                p.name
                for p in self._fs.list_dir(plugin_dir)
                if p.is_file() and p.name.lower().endswith(".jar")
            }
            existing = await repo.list_all_by_server(server_id)
            existing_by_filename = {p.filename: p for p in existing if p.filename}

            added: list[str] = []
            for filename in sorted(disk_files):
                if filename in existing_by_filename:
                    continue
                plugin_id = PluginId()
                plugin = Plugin.install(
                    plugin_id=plugin_id,
                    server_id=server_id,
                    name=filename.rsplit(".", 1)[0],
                    version=PluginVersion(0, 0, 0),
                    description="",
                    author="",
                    website="",
                    source="detected",
                    filename=filename,
                    version_raw="unknown",
                )
                await repo.save(plugin)
                for event in plugin.collect_events():
                    uow.add_event(event)
                added.append(filename)

            removed: list[str] = []
            for plugin in existing:
                if plugin.pending_deletion:
                    continue
                if plugin.filename is None:
                    continue
                if plugin.filename not in disk_files:
                    await repo.delete(plugin.plugin_id)
                    removed.append(plugin.filename)

            await uow.commit()

        if added or removed:
            logger.info(
                "Plugin reconciliation changed filesystem state — server_id=%s added=%s removed=%s",
                str(server_id), added, removed,
            )

        return CommandResult(
            success=True,
            data={"server_id": str(server_id), "added": added, "removed": removed},
        )
