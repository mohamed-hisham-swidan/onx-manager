from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.plugin.domain.aggregate import Plugin
from app.modules.shared.value_objects import PluginId, ServerId


class PluginRepository(ABC):
    @abstractmethod
    async def get(self, plugin_id: PluginId) -> Plugin:
        ...

    @abstractmethod
    async def list_by_server(self, server_id: ServerId) -> list[Plugin]:
        ...

    @abstractmethod
    async def save(self, plugin: Plugin) -> None:
        ...

    @abstractmethod
    async def delete(self, plugin_id: PluginId) -> None:
        ...
