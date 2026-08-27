from __future__ import annotations

import asyncio
import contextlib
import logging
from enum import Enum
from typing import Any

from app.modules.plugin.infrastructure.runner.base import PluginRunner

logger = logging.getLogger(__name__)


class RuntimeStatus(Enum):
    INSTALLED = "installed"
    DISABLED = "disabled"
    ENABLING = "enabling"
    ENABLED = "enabled"
    DISABLING = "disabling"
    UNINSTALLING = "uninstalling"
    UNINSTALLED = "uninstalled"
    FAILED = "failed"


_RUNTIME_TRANSITIONS: dict[RuntimeStatus, set[RuntimeStatus]] = {
    RuntimeStatus.INSTALLED: {
        RuntimeStatus.DISABLED,
        RuntimeStatus.ENABLING,
        RuntimeStatus.UNINSTALLING,
        RuntimeStatus.FAILED,
    },
    RuntimeStatus.DISABLED: {RuntimeStatus.ENABLING, RuntimeStatus.UNINSTALLING},
    RuntimeStatus.ENABLING: {RuntimeStatus.ENABLED, RuntimeStatus.FAILED, RuntimeStatus.DISABLED},
    RuntimeStatus.ENABLED: {RuntimeStatus.DISABLING},
    RuntimeStatus.DISABLING: {RuntimeStatus.DISABLED, RuntimeStatus.FAILED},
    RuntimeStatus.UNINSTALLING: {RuntimeStatus.UNINSTALLED, RuntimeStatus.FAILED},
    RuntimeStatus.UNINSTALLED: set(),
    RuntimeStatus.FAILED: {RuntimeStatus.DISABLED, RuntimeStatus.UNINSTALLING},
}


MAX_RESTART_ATTEMPTS = 3
RESTART_WINDOW_SECONDS = 60
HEARTBEAT_INTERVAL = 5.0
HEARTBEAT_TIMEOUT = 15.0


class PluginLifecycleManager:
    def __init__(self, runner: PluginRunner) -> None:
        self._runner = runner
        self._statuses: dict[str, RuntimeStatus] = {}
        self._restart_counts: dict[str, int] = {}
        self._restart_windows: dict[str, float] = {}
        self._heartbeat_tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def get_status(self, plugin_id: str) -> RuntimeStatus | None:
        async with self._lock:
            return self._statuses.get(plugin_id)

    async def _transition(self, plugin_id: str, target: RuntimeStatus) -> None:
        current = self._statuses.get(plugin_id)
        if current and target not in _RUNTIME_TRANSITIONS.get(current, set()):
            raise ValueError(
                f"Cannot transition from {current.value} to {target.value}",
            )
        self._statuses[plugin_id] = target

    async def install(self, plugin_id: str) -> None:
        async with self._lock:
            self._statuses[plugin_id] = RuntimeStatus.INSTALLED

    async def enable(self, plugin_id: str, plugin_dir: str, manifest: dict[str, Any]) -> None:
        async with self._lock:
            await self._transition(plugin_id, RuntimeStatus.ENABLING)

        try:
            await self._runner.start(plugin_id, plugin_dir, manifest)
            async with self._lock:
                await self._transition(plugin_id, RuntimeStatus.ENABLED)
        except Exception as e:
            logger.error("Failed to enable plugin %s: %s", plugin_id, str(e))
            async with self._lock:
                await self._transition(plugin_id, RuntimeStatus.FAILED)
            raise

        self._start_heartbeat(plugin_id)

    async def disable(self, plugin_id: str) -> None:
        async with self._lock:
            await self._transition(plugin_id, RuntimeStatus.DISABLING)

        self._stop_heartbeat(plugin_id)

        try:
            await self._runner.stop(plugin_id)
        except Exception as e:
            logger.warning("Error stopping plugin %s: %s", plugin_id, str(e))

        async with self._lock:
            await self._transition(plugin_id, RuntimeStatus.DISABLED)

    async def uninstall(self, plugin_id: str) -> None:
        current = await self.get_status(plugin_id)
        if current == RuntimeStatus.ENABLED:
            await self.disable(plugin_id)

        async with self._lock:
            await self._transition(plugin_id, RuntimeStatus.UNINSTALLING)

        async with self._lock:
            await self._transition(plugin_id, RuntimeStatus.UNINSTALLED)
        self._cleanup(plugin_id)

    async def check_health(self, plugin_id: str) -> bool:
        try:
            return await self._runner.health(plugin_id)
        except Exception:
            return False

    async def on_heartbeat_missed(self, plugin_id: str) -> None:
        now = asyncio.get_event_loop().time()

        async with self._lock:
            count = self._restart_counts.get(plugin_id, 0)
            window_start = self._restart_windows.get(plugin_id, now)

            if now - window_start > RESTART_WINDOW_SECONDS:
                count = 0
                window_start = now

            count += 1
            self._restart_counts[plugin_id] = count
            self._restart_windows[plugin_id] = window_start

            if count > MAX_RESTART_ATTEMPTS:
                await self._transition(plugin_id, RuntimeStatus.FAILED)
                logger.error("Plugin %s failed after %d restart attempts", plugin_id, count)
                return

            logger.warning(
                "Plugin %s heartbeat missed, restarting (attempt %d/%d)",
                plugin_id,
                count,
                MAX_RESTART_ATTEMPTS,
            )
            await self._transition(plugin_id, RuntimeStatus.DISABLING)

        self._stop_heartbeat(plugin_id)

        with contextlib.suppress(Exception):
            await self._runner.stop(plugin_id)

        async with self._lock:
            await self._transition(plugin_id, RuntimeStatus.DISABLED)

    async def mark_failed(self, plugin_id: str) -> None:
        async with self._lock:
            await self._transition(plugin_id, RuntimeStatus.FAILED)
        self._stop_heartbeat(plugin_id)

    def _start_heartbeat(self, plugin_id: str) -> None:
        self._stop_heartbeat(plugin_id)

        async def heartbeat_loop() -> None:
            missed = 0
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                try:
                    alive = await self.check_health(plugin_id)
                    if alive:
                        missed = 0
                    else:
                        missed += 1
                        if missed * HEARTBEAT_INTERVAL >= HEARTBEAT_TIMEOUT:
                            await self.on_heartbeat_missed(plugin_id)
                            return
                except asyncio.CancelledError:
                    return
                except Exception:
                    missed += 1
                    if missed * HEARTBEAT_INTERVAL >= HEARTBEAT_TIMEOUT:
                        await self.on_heartbeat_missed(plugin_id)
                        return

        self._heartbeat_tasks[plugin_id] = asyncio.create_task(heartbeat_loop())

    def _stop_heartbeat(self, plugin_id: str) -> None:
        task = self._heartbeat_tasks.pop(plugin_id, None)
        if task is not None and not task.done():
            task.cancel()

    def _cleanup(self, plugin_id: str) -> None:
        self._stop_heartbeat(plugin_id)
        self._statuses.pop(plugin_id, None)
        self._restart_counts.pop(plugin_id, None)
        self._restart_windows.pop(plugin_id, None)
