from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from app.core.exceptions import InvalidValueError
from app.modules.plugin.domain.events import (
    PluginDisabledEvent,
    PluginEnabledEvent,
    PluginInstalledEvent,
    PluginUninstalledEvent,
    PluginUpdatedEvent,
)
from app.modules.shared.aggregate import AggregateRoot
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId


class PluginStatus(Enum):
    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"
    UNINSTALLED = "uninstalled"


_PLUGIN_TRANSITIONS: dict[PluginStatus, set[PluginStatus]] = {
    PluginStatus.INSTALLED: {PluginStatus.ENABLED, PluginStatus.DISABLED},
    PluginStatus.ENABLED: {PluginStatus.DISABLED, PluginStatus.ERROR},
    PluginStatus.DISABLED: {PluginStatus.ENABLED},
    PluginStatus.ERROR: {PluginStatus.DISABLED, PluginStatus.ENABLED},
}


class Plugin(AggregateRoot):
    def __init__(
        self,
        plugin_id: PluginId,
        server_id: ServerId,
        name: str,
        version: PluginVersion,
        description: str = "",
        author: str = "",
        website: str = "",
        dependencies: list[str] | None = None,
        status: PluginStatus = PluginStatus.INSTALLED,
        source: str = "manual",
        filename: str | None = None,
        pending_deletion: bool = False,
        pending_deletion_requested_at: datetime | None = None,
        external_project_id: str | None = None,
        external_version_id: str | None = None,
        external_url: str | None = None,
        checksum: str | None = None,
        version_raw: str | None = None,
        installed_at: datetime | None = None,
        updated_at: datetime | None = None,
        project_type: str = "plugin",
        icon_url: str | None = None,
    ) -> None:
        super().__init__()
        self._plugin_id = plugin_id
        self._server_id = server_id
        self._name = name
        self._version = version
        self._version_raw = version_raw
        self._description = description
        self._author = author
        self._website = website
        self._dependencies = dependencies or []
        self._status = status
        self._source = source
        self._filename = filename
        self._pending_deletion = pending_deletion
        self._pending_deletion_requested_at = pending_deletion_requested_at
        self._external_project_id = external_project_id
        self._external_version_id = external_version_id
        self._external_url = external_url
        self._checksum = checksum
        now = datetime.now(timezone.utc)
        self._installed_at = installed_at or now
        self._updated_at = updated_at or now
        self._project_type = project_type
        self._icon_url = icon_url

    @property
    def plugin_id(self) -> PluginId:
        return self._plugin_id

    @property
    def server_id(self) -> ServerId:
        return self._server_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> PluginVersion:
        return self._version

    @property
    def display_version(self) -> str:
        return self._version_raw or str(self._version)

    @property
    def source(self) -> str:
        return self._source

    @property
    def project_type(self) -> str:
        return self._project_type

    @property
    def filename(self) -> str | None:
        return self._filename

    @property
    def pending_deletion(self) -> bool:
        return self._pending_deletion

    @property
    def pending_deletion_requested_at(self) -> datetime | None:
        return self._pending_deletion_requested_at

    @property
    def external_project_id(self) -> str | None:
        return self._external_project_id

    @property
    def external_version_id(self) -> str | None:
        return self._external_version_id

    @property
    def external_url(self) -> str | None:
        return self._external_url

    @property
    def checksum(self) -> str | None:
        return self._checksum

    @property
    def icon_url(self) -> str | None:
        return self._icon_url

    @property
    def description(self) -> str:
        return self._description

    @property
    def author(self) -> str:
        return self._author

    @property
    def website(self) -> str:
        return self._website

    @property
    def dependencies(self) -> list[str]:
        return list(self._dependencies)

    @property
    def status(self) -> PluginStatus:
        return self._status

    @property
    def installed_at(self) -> datetime:
        return self._installed_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    @classmethod
    def install(
        cls,
        plugin_id: PluginId,
        server_id: ServerId,
        name: str,
        version: PluginVersion,
        description: str = "",
        author: str = "",
        website: str = "",
        dependencies: list[str] | None = None,
        source: str = "manual",
        filename: str | None = None,
        external_project_id: str | None = None,
        external_version_id: str | None = None,
        external_url: str | None = None,
        checksum: str | None = None,
        version_raw: str | None = None,
        project_type: str = "plugin",
        icon_url: str | None = None,
    ) -> Plugin:
        plugin = cls(
            plugin_id=plugin_id,
            server_id=server_id,
            name=name,
            version=version,
            description=description,
            author=author,
            website=website,
            dependencies=dependencies,
            source=source,
            filename=filename,
            external_project_id=external_project_id,
            external_version_id=external_version_id,
            external_url=external_url,
            checksum=checksum,
            version_raw=version_raw,
            project_type=project_type,
            icon_url=icon_url,
        )
        plugin._add_event(
            PluginInstalledEvent(
                plugin_id=str(plugin_id),
                server_id=str(server_id),
                version=str(version),
            ),
        )
        return plugin

    def _transition_to(self, new_status: PluginStatus) -> None:
        allowed = _PLUGIN_TRANSITIONS.get(self._status, set())
        if new_status not in allowed:
            raise InvalidValueError(
                field="status",
                value=new_status.value,
                reason=f"Cannot transition from {self._status.value} to {new_status.value}",
            )
        self._status = new_status
        self._updated_at = datetime.now(timezone.utc)

    def enable(self) -> None:
        self._transition_to(PluginStatus.ENABLED)
        self._add_event(PluginEnabledEvent(plugin_id=str(self._plugin_id), server_id=str(self._server_id)))

    def disable(self) -> None:
        self._transition_to(PluginStatus.DISABLED)
        self._add_event(PluginDisabledEvent(plugin_id=str(self._plugin_id), server_id=str(self._server_id)))

    def mark_error(self) -> None:
        self._transition_to(PluginStatus.ERROR)

    def update_version(self, new_version: PluginVersion, version_raw: str | None = None) -> None:
        old = self._version
        self._version = new_version
        self._version_raw = version_raw
        self._updated_at = datetime.now(timezone.utc)
        self._add_event(
            PluginUpdatedEvent(
                plugin_id=str(self._plugin_id),
                server_id=str(self._server_id),
                old_version=str(old),
                new_version=str(new_version),
            ),
        )

    def mark_uninstalled(self) -> None:
        self._add_event(
            PluginUninstalledEvent(plugin_id=str(self._plugin_id), server_id=str(self._server_id)),
        )

    def request_deletion(self) -> None:
        """Mark this plugin as pending deletion.

        The DB row is kept and flagged; the actual file is only removed from
        disk on the next server start/restart by the deferred-deletion flow,
        so a running JVM never has its .jar removed out from under it.
        """
        self._pending_deletion = True
        self._pending_deletion_requested_at = datetime.now(timezone.utc)
        self._updated_at = datetime.now(timezone.utc)
        self._add_event(
            PluginUninstalledEvent(plugin_id=str(self._plugin_id), server_id=str(self._server_id)),
        )


class DependencyStatus(Enum):
    SATISFIED = "satisfied"
    MISSING = "missing"
    INCOMPATIBLE = "incompatible"
    CIRCULAR = "circular"


class PluginRegistry(AggregateRoot):
    def __init__(self, server_id: ServerId) -> None:
        super().__init__()
        self._server_id = server_id
        self._plugins: dict[str, Plugin] = {}

    @property
    def server_id(self) -> ServerId:
        return self._server_id

    @property
    def plugins(self) -> list[Plugin]:
        return list(self._plugins.values())

    def add_plugin(self, plugin: Plugin) -> None:
        self._plugins[str(plugin.plugin_id)] = plugin

    def remove_plugin(self, plugin_id: PluginId) -> None:
        self._plugins.pop(str(plugin_id), None)

    def get_plugin(self, plugin_id: PluginId) -> Plugin | None:
        return self._plugins.get(str(plugin_id))

    def get_by_name(self, name: str) -> Plugin | None:
        for plugin in self._plugins.values():
            if plugin.name == name:
                return plugin
        return None

    def check_dependencies(self, plugin: Plugin) -> dict[str, DependencyStatus]:
        result: dict[str, DependencyStatus] = {}
        visited: set[str] = set()

        def resolve(name: str, chain: set[str]) -> DependencyStatus:
            if name in chain:
                return DependencyStatus.CIRCULAR
            dep = self.get_by_name(name)
            if dep is None:
                return DependencyStatus.MISSING
            if dep.status != PluginStatus.ENABLED:
                return DependencyStatus.INCOMPATIBLE
            for sub_dep in dep.dependencies:
                sub_result = resolve(sub_dep, chain | {name})
                if sub_result != DependencyStatus.SATISFIED:
                    return sub_result
            return DependencyStatus.SATISFIED

        for dep_name in plugin.dependencies:
            visited.clear()
            result[dep_name] = resolve(dep_name, set())

        return result

    def can_enable(self, plugin: Plugin) -> bool:
        deps = self.check_dependencies(plugin)
        return all(s == DependencyStatus.SATISFIED for s in deps.values())
