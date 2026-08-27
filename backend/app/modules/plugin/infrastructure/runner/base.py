from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PluginRunner(ABC):
    @abstractmethod
    async def start(self, plugin_id: str, plugin_dir: str, manifest: dict[str, Any]) -> None: ...

    @abstractmethod
    async def stop(self, plugin_id: str) -> None: ...

    @abstractmethod
    async def restart(self, plugin_id: str) -> None: ...

    @abstractmethod
    async def health(self, plugin_id: str) -> bool: ...

    @abstractmethod
    async def execute_hook(self, plugin_id: str, hook: str, payload: dict[str, Any]) -> Any: ...
