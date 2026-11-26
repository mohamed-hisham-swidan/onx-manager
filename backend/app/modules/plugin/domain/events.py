from __future__ import annotations

from typing import Any

from app.core.event_bus import DomainEvent


class PluginInstalledEvent(DomainEvent):
    plugin_id: str
    server_id: str
    version: str
    name: str | None = None
    filename: str | None = None

    def __init__(
        self,
        plugin_id: str,
        server_id: str,
        version: str,
        name: str | None = None,
        filename: str | None = None,
        **data: Any,
    ) -> None:
        resolved_filename = filename or data.pop("file_name", None)
        super().__init__(
            plugin_id=plugin_id,
            server_id=server_id,
            version=version,
            name=name,
            filename=resolved_filename,
            **data,
        )


class PluginEnabledEvent(DomainEvent):
    plugin_id: str
    server_id: str
    name: str | None = None
    filename: str | None = None

    def __init__(
        self,
        plugin_id: str,
        server_id: str,
        name: str | None = None,
        filename: str | None = None,
        **data: Any,
    ) -> None:
        super().__init__(
            plugin_id=plugin_id,
            server_id=server_id,
            name=name,
            filename=filename,
            **data,
        )


class PluginDisabledEvent(DomainEvent):
    plugin_id: str
    server_id: str
    name: str | None = None
    filename: str | None = None

    def __init__(
        self,
        plugin_id: str,
        server_id: str,
        name: str | None = None,
        filename: str | None = None,
        **data: Any,
    ) -> None:
        super().__init__(
            plugin_id=plugin_id,
            server_id=server_id,
            name=name,
            filename=filename,
            **data,
        )


class PluginUninstalledEvent(DomainEvent):
    plugin_id: str
    server_id: str
    name: str | None = None
    filename: str | None = None

    def __init__(
        self,
        plugin_id: str,
        server_id: str,
        name: str | None = None,
        filename: str | None = None,
        **data: Any,
    ) -> None:
        super().__init__(
            plugin_id=plugin_id,
            server_id=server_id,
            name=name,
            filename=filename,
            **data,
        )


class PluginUpdatedEvent(DomainEvent):
    plugin_id: str
    server_id: str
    old_version: str
    new_version: str
    name: str | None = None
    filename: str | None = None

    def __init__(
        self,
        plugin_id: str,
        server_id: str,
        old_version: str,
        new_version: str,
        name: str | None = None,
        filename: str | None = None,
        **data: Any,
    ) -> None:
        super().__init__(
            plugin_id=plugin_id,
            server_id=server_id,
            old_version=old_version,
            new_version=new_version,
            name=name,
            filename=filename,
            **data,
        )
