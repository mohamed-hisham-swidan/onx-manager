from __future__ import annotations

from typing import Any

from app.core.event_bus import DomainEvent


class PluginInstalledEvent(DomainEvent):
    plugin_id: str
    server_id: str
    version: str

    def __init__(self, plugin_id: str, server_id: str, version: str, **data: Any) -> None:
        super().__init__(plugin_id=plugin_id, server_id=server_id, version=version, **data)


class PluginEnabledEvent(DomainEvent):
    plugin_id: str
    server_id: str

    def __init__(self, plugin_id: str, server_id: str, **data: Any) -> None:
        super().__init__(plugin_id=plugin_id, server_id=server_id, **data)


class PluginDisabledEvent(DomainEvent):
    plugin_id: str
    server_id: str

    def __init__(self, plugin_id: str, server_id: str, **data: Any) -> None:
        super().__init__(plugin_id=plugin_id, server_id=server_id, **data)


class PluginUninstalledEvent(DomainEvent):
    plugin_id: str
    server_id: str

    def __init__(self, plugin_id: str, server_id: str, **data: Any) -> None:
        super().__init__(plugin_id=plugin_id, server_id=server_id, **data)


class PluginUpdatedEvent(DomainEvent):
    plugin_id: str
    server_id: str
    old_version: str
    new_version: str

    def __init__(self, plugin_id: str, server_id: str, old_version: str, new_version: str, **data: Any) -> None:
        super().__init__(plugin_id=plugin_id, server_id=server_id, old_version=old_version, new_version=new_version, **data)
