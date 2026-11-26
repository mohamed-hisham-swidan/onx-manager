from __future__ import annotations

import logging
import os

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.plugin.domain.aggregate import Plugin
from app.modules.plugin.domain.repository import PluginRepository
from app.modules.plugin.infrastructure.addon_fs import (
    get_addon_dir_name,
    sanitize_addon_filename,
)
from app.modules.plugin.infrastructure.jar_metadata_parser import validate_addon_jar
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.fs import FileSystem, local_fs
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId

logger = logging.getLogger(__name__)


class UploadModCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    filename: str
    file_content: bytes


class UploadModHandler(CommandHandler[UploadModCommand]):
    def __init__(self, event_bus: EventBus, fs: FileSystem | None = None) -> None:
        self._event_bus = event_bus
        self._fs = fs or local_fs

    async def handle(self, command: UploadModCommand) -> CommandResult:
        server_id = ServerId(command.server_id)

        async with UnitOfWork(self._event_bus) as uow:
            server_repo: ServerRepository = SQLServerRepository(uow.session)
            server = await server_repo.get(server_id)

            if server.deployment is None or not server.deployment.root_path:
                return CommandResult(
                    success=False,
                    error="Server has no deployment; cannot resolve addon directory.",
                    error_code="NO_DEPLOYMENT",
                )

            server_type = server.server_type.value
            meta = validate_addon_jar(
                command.filename,
                command.file_content,
                server_type=server_type,
            )

            addon_dir_name = get_addon_dir_name(server_type)
            addon_dir = os.path.join(server.deployment.server_directory(), addon_dir_name)

            if not self._fs.exists(addon_dir):
                self._fs.ensure_dir(addon_dir)

            target_path = sanitize_addon_filename(command.filename, addon_dir)
            target_path_str = str(target_path)
            disabled_path_str = f"{target_path_str}.disabled"

            repo: PluginRepository = SQLPluginRepository(uow.session)
            existing_rows = [
                p
                for p in await repo.list_all_by_server(server_id)
                if p.filename == target_path.name
            ]
            pending_rows = [p for p in existing_rows if p.pending_deletion]
            if pending_rows and len(pending_rows) == len(existing_rows):
                for stale_path in (target_path_str, disabled_path_str):
                    if self._fs.exists(stale_path):
                        self._fs.delete(stale_path)
                for p in pending_rows:
                    await repo.delete(p.plugin_id)

            if self._fs.exists(target_path_str) or self._fs.exists(disabled_path_str):
                return CommandResult(
                    success=False,
                    error=(
                        f"A file named '{target_path.name}' already exists "
                        f"in the {addon_dir_name} folder."
                    ),
                    error_code="FILE_ALREADY_EXISTS",
                )

            self._fs.write_binary_atomic(target_path_str, command.file_content)

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

            mod_name = meta.name or meta.mod_id or target_path.stem
            project_type = "mod" if addon_dir_name == "mods" else "plugin"
            plugin_id = PluginId()

            plugin = Plugin.install(
                plugin_id=plugin_id,
                server_id=server_id,
                name=mod_name,
                version=parsed_ver,
                description=meta.description or "",
                author=", ".join(meta.authors) if meta.authors else "",
                website=meta.website or "",
                dependencies=meta.dependencies,
                source="upload",
                filename=target_path.name,
                version_raw=ver_raw,
                project_type=project_type,
                loader=meta.loader,
                mod_id=meta.mod_id,
                is_disabled_on_disk=False,
            )

            await repo.save(plugin)
            for event in plugin.collect_events():
                uow.add_event(event)
            await uow.commit()

        data: dict = {
            "plugin_id": str(plugin_id),
            "server_id": str(server_id),
            "name": mod_name,
            "version": ver_raw or str(parsed_ver),
            "filename": target_path.name,
            "source": "upload",
            "loader": meta.loader,
            "mod_id": meta.mod_id,
            "is_disabled_on_disk": False,
            "is_client_only": meta.is_client_only,
            "warning": meta.warning,
        }
        return CommandResult(success=True, data=data)
