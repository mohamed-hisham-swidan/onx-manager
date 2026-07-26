from __future__ import annotations

from typing import Any

from app.modules.plugin.infrastructure.runner.base import PluginRunner


class ContainerPluginRunner(PluginRunner):
    async def start(self, plugin_id: str, plugin_dir: str, manifest: dict[str, Any]) -> None:
        raise NotImplementedError("Container isolation not yet implemented")

    async def stop(self, plugin_id: str) -> None:
        raise NotImplementedError("Container isolation not yet implemented")

    async def restart(self, plugin_id: str) -> None:
        raise NotImplementedError("Container isolation not yet implemented")

    async def health(self, plugin_id: str) -> bool:
        raise NotImplementedError("Container isolation not yet implemented")

    async def execute_hook(self, plugin_id: str, hook: str, payload: dict[str, Any]) -> Any:
        raise NotImplementedError("Container isolation not yet implemented")
