from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.plugin.domain.aggregate import Plugin, PluginStatus
from app.modules.plugin.domain.repository import PluginRepository
from app.modules.plugin.infrastructure.jar_metadata_parser import (
    ModMetadata,
    parse_jar_metadata,
)
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.fs import FileSystem, local_fs
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId

logger = logging.getLogger(__name__)


@dataclass
class _DiskAddon:
    dir_name: str
    base_filename: str
    actual_filename: str
    full_path: str
    is_disabled: bool


class ReconcilePluginsCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str


class ReconcilePluginsHandler(CommandHandler[ReconcilePluginsCommand]):
    """Make the plugins DB table reflect the actual filesystem state.

    The filesystem (``<server_dir>/plugins/*.jar`` and ``<server_dir>/mods/*.jar``,
    along with their ``.jar.disabled`` variants) is the source of truth for which
    plugins/mods exist. The DB is a metadata cache layered on top of it.
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

            server_dir = server.deployment.server_directory()
            repo: PluginRepository = SQLPluginRepository(uow.session)

            disk_addons: dict[str, _DiskAddon] = {}
            for dir_name in ("plugins", "mods"):
                dir_path = os.path.join(server_dir, dir_name)
                if not self._fs.exists(dir_path):
                    continue

                for p in self._fs.list_dir(dir_path):
                    if not p.is_file():
                        continue
                    name = p.name
                    lower_name = name.lower()
                    if lower_name.endswith(".jar.disabled"):
                        base_name = name[:-9]
                        is_disabled = True
                    elif lower_name.endswith(".jar"):
                        base_name = name
                        is_disabled = False
                    else:
                        continue

                    disk_addons[base_name] = _DiskAddon(
                        dir_name=dir_name,
                        base_filename=base_name,
                        actual_filename=name,
                        full_path=os.path.join(dir_path, name),
                        is_disabled=is_disabled,
                    )

            existing = await repo.list_all_by_server(server_id)
            existing_by_filename = {p.filename: p for p in existing if p.filename}

            added: list[str] = []
            for base_name, disk_addon in sorted(disk_addons.items()):
                if base_name in existing_by_filename:
                    existing_plugin = existing_by_filename[base_name]
                    # Check disk disabled state drift
                    if disk_addon.is_disabled and not existing_plugin.is_disabled_on_disk:
                        existing_plugin.set_disabled_on_disk(True)
                        existing_plugin.disable()
                        await repo.save(existing_plugin)
                    elif not disk_addon.is_disabled and existing_plugin.is_disabled_on_disk:
                        existing_plugin.set_disabled_on_disk(False)
                        existing_plugin.enable()
                        await repo.save(existing_plugin)

                    # Update missing metadata if unknown
                    if existing_plugin.display_version == "unknown" or not existing_plugin.loader:
                        try:
                            meta = parse_jar_metadata(disk_addon.full_path)
                            if meta.version and existing_plugin.display_version == "unknown":
                                try:
                                    parsed_ver = PluginVersion.parse(meta.version)
                                    ver_raw = None
                                except ValueError:
                                    parsed_ver = PluginVersion(0, 0, 0)
                                    ver_raw = meta.version
                                existing_plugin.update_version(parsed_ver, version_raw=ver_raw)
                            if meta.loader and not existing_plugin.loader:
                                existing_plugin._loader = meta.loader
                            if meta.mod_id and not existing_plugin.mod_id:
                                existing_plugin._mod_id = meta.mod_id
                            await repo.save(existing_plugin)
                        except Exception as e:
                            logger.debug(
                                "Failed parsing metadata for %s: %s",
                                disk_addon.full_path,
                                e,
                            )
                    continue

                # New addon detected on disk
                try:
                    meta = parse_jar_metadata(disk_addon.full_path)
                except Exception as e:
                    logger.debug(
                        "Failed parsing metadata for new addon %s: %s",
                        disk_addon.full_path,
                        e,
                    )
                    meta = ModMetadata(name=base_name.rsplit(".", 1)[0])

                parsed_raw = meta.version
                if parsed_raw:
                    try:
                        parsed_ver = PluginVersion.parse(parsed_raw)
                        ver_raw = None
                    except ValueError:
                        parsed_ver = PluginVersion(0, 0, 0)
                        ver_raw = parsed_raw
                else:
                    parsed_ver = PluginVersion(0, 0, 0)
                    ver_raw = "unknown"

                plugin_id = PluginId()
                mod_name = meta.name or meta.mod_id or base_name.rsplit(".", 1)[0]
                project_type = "mod" if disk_addon.dir_name == "mods" else "plugin"

                plugin = Plugin.install(
                    plugin_id=plugin_id,
                    server_id=server_id,
                    name=mod_name,
                    version=parsed_ver,
                    description=meta.description or "",
                    author=", ".join(meta.authors) if meta.authors else "",
                    website=meta.website or "",
                    dependencies=meta.dependencies,
                    source="detected",
                    filename=base_name,
                    version_raw=ver_raw,
                    project_type=project_type,
                    loader=meta.loader,
                    mod_id=meta.mod_id,
                    is_disabled_on_disk=disk_addon.is_disabled,
                )
                if disk_addon.is_disabled:
                    plugin._status = PluginStatus.DISABLED

                await repo.save(plugin)
                for event in plugin.collect_events():
                    uow.add_event(event)
                added.append(base_name)

            removed: list[str] = []
            for plugin in existing:
                if plugin.pending_deletion:
                    continue
                if plugin.filename is None:
                    continue
                if plugin.filename not in disk_addons:
                    await repo.delete(plugin.plugin_id)
                    removed.append(plugin.filename)

            await uow.commit()

        if added or removed:
            logger.info(
                "Plugin reconciliation changed filesystem state — server_id=%s added=%s removed=%s",
                str(server_id),
                added,
                removed,
            )

        return CommandResult(
            success=True,
            data={"server_id": str(server_id), "added": added, "removed": removed},
        )
