from __future__ import annotations

import contextlib
import logging
import os

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import (
    CorruptedDownloadError,
    DownloadError,
    DownloadTimeoutError,
    InvalidValueError,
    ProviderError,
)
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.plugin.application.services.version_selector import (
    VersionSelection,
    select_best_version,
)
from app.modules.plugin.domain.aggregate import Plugin
from app.modules.plugin.domain.repository import PluginRepository
from app.modules.plugin.infrastructure.addon_fs import (
    get_addon_dir_name,
    sanitize_addon_filename,
)
from app.modules.plugin.infrastructure.jar_metadata_parser import parse_jar_metadata
from app.modules.plugin.infrastructure.providers import build_plugin_catalog_provider
from app.modules.plugin.infrastructure.providers.base import PluginFile, PluginVersionInfo
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.infrastructure.fs import FileSystem, local_fs
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId

logger = logging.getLogger(__name__)

# Server types that do NOT support plugin/mod catalog installation.
_MANUAL_SERVER_TYPES = {"vanilla"}


class InstallModrinthPluginCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    project_id: str
    version_id: str | None = None
    minecraft_version: str | None = None


class InstallModrinthPluginHandler(CommandHandler[InstallModrinthPluginCommand]):
    def __init__(
        self,
        event_bus: EventBus,
        fs: FileSystem | None = None,
        provider=None,
    ) -> None:
        self._event_bus = event_bus
        self._fs = fs or local_fs
        self._provider = provider

    async def handle(self, command: InstallModrinthPluginCommand) -> CommandResult:
        server_id = ServerId(command.server_id)
        provider = self._provider or build_plugin_catalog_provider()

        async with UnitOfWork(self._event_bus) as uow:
            server_repo: ServerRepository = SQLServerRepository(uow.session)
            server = await server_repo.get(server_id)

            if server.deployment is None or not server.deployment.root_path:
                return CommandResult(
                    success=False,
                    error="Server has no deployment; cannot resolve plugin directory.",
                    error_code="NO_DEPLOYMENT",
                )

            server_type = server.server_type.value
            minecraft_version = command.minecraft_version or str(server.minecraft_version)

            if not _server_supports_plugins(server_type):
                return CommandResult(
                    success=False,
                    error=(
                        f"Server type '{server_type}' does not support plugin installs "
                        "from a catalog. Install plugins manually."
                    ),
                    error_code="PLUGINS_UNSUPPORTED",
                )

            selection = await self._resolve_version(
                provider=provider,
                server_type=server_type,
                minecraft_version=minecraft_version,
                project_id=command.project_id,
                version_id=command.version_id,
            )
            if selection.selected is None:
                return CommandResult(
                    success=False,
                    error=selection.notice or "No compatible plugin version found.",
                    error_code="NO_COMPATIBLE_VERSION",
                )

            version = selection.selected
            plugin_file = _pick_primary_file(version)

            raw_filename = plugin_file.filename
            if (
                not raw_filename
                or ".." in raw_filename
                or "/" in raw_filename
                or "\\" in raw_filename
            ):
                return CommandResult(
                    success=False,
                    error=(
                        f"Invalid plugin filename '{raw_filename}': "
                        "path traversal or separator detected"
                    ),
                    error_code="INVALID_FILENAME",
                )

            addon_dir_name = get_addon_dir_name(server_type)
            plugin_dir = os.path.join(server.deployment.server_directory(), addon_dir_name)
            try:
                target_path = sanitize_addon_filename(raw_filename, plugin_dir)
            except InvalidValueError as e:
                return CommandResult(
                    success=False,
                    error=f"Invalid plugin filename '{raw_filename}': {e.message}",
                    error_code="INVALID_FILENAME",
                )

            safe_filename = target_path.name
            if not self._fs.exists(plugin_dir):
                self._fs.ensure_dir(plugin_dir)
            dest = str(target_path)

            resolved_plugin_dir = os.path.abspath(plugin_dir)
            resolved_dest = os.path.abspath(dest)
            if os.path.commonpath([resolved_plugin_dir, resolved_dest]) != resolved_plugin_dir:
                return CommandResult(
                    success=False,
                    error=f"Invalid destination path '{safe_filename}'",
                    error_code="INVALID_FILENAME",
                )

            if self._fs.exists(dest):
                return CommandResult(
                    success=False,
                    error=(
                        f"A file named '{safe_filename}' already exists "
                        f"in the {addon_dir_name} folder."
                    ),
                    error_code="FILE_CONFLICT",
                )

            try:
                if not plugin_file.sha1 and not plugin_file.sha512:
                    raise CorruptedDownloadError(
                        plugin_file.url,
                        "catalog supplied neither sha1 nor sha512 checksum for verification",
                    )
                content = await provider.download(
                    plugin_file.url,
                    expected_sha1=plugin_file.sha1 or None,
                    expected_sha512=plugin_file.sha512 or None,
                )
            except (DownloadError, DownloadTimeoutError, CorruptedDownloadError) as e:
                return CommandResult(
                    success=False,
                    error=f"Failed to download plugin: {e}",
                    error_code="DOWNLOAD_FAILED",
                )

            try:
                self._fs.ensure_dir(plugin_dir)
                self._fs.write_binary_atomic(dest, content)
            except OSError as e:
                return CommandResult(
                    success=False,
                    error=f"Failed to write plugin file: {e}",
                    error_code="WRITE_FAILED",
                )

            try:
                parsed_version = PluginVersion.parse(version.version_number)
                version_raw = None
            except ValueError:
                parsed_version = PluginVersion(0, 0, 0)
                version_raw = version.version_number

            icon_url = None
            try:
                project_info = await provider.get_project(command.project_id)
                icon_url = project_info.icon_url or None
            except Exception as e:
                logger.warning("Failed to fetch project info to get icon_url: %s", e)

            meta = None
            with contextlib.suppress(Exception):
                meta = parse_jar_metadata(content)

            project_type = "mod" if addon_dir_name == "mods" else "plugin"
            loader = (
                (meta.loader if meta else None)
                or (version.loaders[0] if version.loaders else None)
            )
            mod_id = meta.mod_id if meta else None
            warning = meta.warning if meta else None

            plugin_id = PluginId()
            plugin = Plugin.install(
                plugin_id=plugin_id,
                server_id=server_id,
                name=version.name or command.project_id,
                version=parsed_version,
                description="",
                author="",
                website="",
                source=provider.name,
                filename=plugin_file.filename,
                external_project_id=command.project_id,
                external_version_id=version.version_id,
                external_url=plugin_file.url,
                checksum=plugin_file.sha1 or plugin_file.sha512 or None,
                version_raw=version_raw,
                icon_url=icon_url,
                project_type=project_type,
                loader=loader,
                mod_id=mod_id,
                is_disabled_on_disk=False,
            )
            repo: PluginRepository = SQLPluginRepository(uow.session)
            await repo.save(plugin)
            for event in plugin.collect_events():
                uow.add_event(event)
            await uow.commit()

        data: dict = {
            "plugin_id": str(plugin_id),
            "version": version.version_number,
            "filename": plugin_file.filename,
            "source": provider.name,
            "notice": selection.notice,
            "notice_kind": selection.notice_kind,
            "loader": loader,
            "mod_id": mod_id,
            "warning": warning,
        }
        return CommandResult(success=True, data=data)

    async def _resolve_version(
        self,
        provider,
        server_type: str,
        minecraft_version: str,
        project_id: str,
        version_id: str | None,
    ) -> VersionSelection:
        if version_id:
            try:
                version = await provider.get_version(version_id)
            except (DownloadError, DownloadTimeoutError) as e:
                raise ProviderError(provider.name, "fetch-version", str(e)) from e
            if version.project_id != project_id:
                return VersionSelection(
                    selected=None,
                    available=(),
                    notice="Requested version does not belong to this project.",
                    notice_kind="incompatible",
                )
            return VersionSelection(selected=version, available=(version,))

        try:
            page = await provider.get_project_versions(project_id)
        except (DownloadError, DownloadTimeoutError) as e:
            raise ProviderError(provider.name, "fetch-versions", str(e)) from e

        return select_best_version(server_type, minecraft_version, page.items)


def _pick_primary_file(version: PluginVersionInfo) -> PluginFile:
    for f in version.files:
        if f.primary:
            return f
    if version.files:
        return version.files[0]
    raise InvalidValueError(
        field="version.files",
        value=version.version_id,
        reason="version has no downloadable file",
    )


def _server_supports_plugins(server_type: str) -> bool:
    return server_type not in _MANUAL_SERVER_TYPES
