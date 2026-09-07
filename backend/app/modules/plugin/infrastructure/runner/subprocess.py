from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from typing import Any

from app.modules.plugin.infrastructure.runner.base import PluginRunner

logger = logging.getLogger(__name__)


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


class JsonRpcClient:
    def __init__(self) -> None:
        self._request_id = 0

    def build_request(self, method: str, params: dict[str, Any] | None = None) -> str:
        self._request_id += 1
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": params or {},
            }
        )

    def parse_response(self, raw: str) -> Any:
        data = json.loads(raw)
        if "error" in data:
            err = data["error"]
            raise JsonRpcError(
                err.get("code", -1), err.get("message", "Unknown error"), err.get("data")
            )
        return data.get("result")


class SubprocessPluginRunner(PluginRunner):
    def __init__(self, heartbeat_interval: float = 5.0) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._plugin_configs: dict[str, tuple[str, dict[str, Any]]] = {}
        self._rpc = JsonRpcClient()
        self._heartbeat_interval = heartbeat_interval
        self._lock = asyncio.Lock()

    async def start(self, plugin_id: str, plugin_dir: str, manifest: dict[str, Any]) -> None:
        entry_point = manifest.get("entry_point", "main.py")
        script_path = os.path.join(plugin_dir, entry_point)

        if not os.path.exists(script_path):
            raise FileNotFoundError(f"Plugin entry point not found: {script_path}")

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            script_path,
            "--plugin-id",
            plugin_id,
            "--plugin-dir",
            plugin_dir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=plugin_dir,
        )

        async with self._lock:
            self._processes[plugin_id] = proc
            self._plugin_configs[plugin_id] = (plugin_dir, manifest)

        logger.info("Plugin %s started (pid=%d)", plugin_id, proc.pid)

        hello = await self._read_line(proc)
        if hello:
            response = self._rpc.parse_response(hello)
            logger.info("Plugin %s initialised: %s", plugin_id, response)

    async def stop(self, plugin_id: str) -> None:
        async with self._lock:
            proc = self._processes.pop(plugin_id, None)

        if proc is None:
            return

        try:
            req = self._rpc.build_request("shutdown")
            await self._write_line(proc, req)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
                logger.info("Plugin %s shut down gracefully", plugin_id)
                return
            except TimeoutError:
                pass

            proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass

    async def restart(self, plugin_id: str) -> None:
        async with self._lock:
            config = self._plugin_configs.get(plugin_id)
        await self.stop(plugin_id)
        if config:
            plugin_dir, manifest = config
            await self.start(plugin_id, plugin_dir, manifest)
        logger.info("Plugin %s restarted", plugin_id)

    async def health(self, plugin_id: str) -> bool:
        async with self._lock:
            proc = self._processes.get(plugin_id)

        if proc is None:
            return False

        if proc.returncode is not None:
            return False

        try:
            req = self._rpc.build_request("ping")
            await self._write_line(proc, req)
            raw = await asyncio.wait_for(self._read_line(proc), timeout=3.0)
            if raw:
                result = self._rpc.parse_response(raw)
                return result is True or result == "pong"
        except (TimeoutError, JsonRpcError, Exception) as e:
            logger.debug("Health check failed for plugin %s: %s", plugin_id, str(e))

        return False

    async def execute_hook(self, plugin_id: str, hook: str, payload: dict[str, Any]) -> Any:
        async with self._lock:
            proc = self._processes.get(plugin_id)

        if proc is None:
            raise RuntimeError(f"Plugin {plugin_id} not running")

        req = self._rpc.build_request("hook", {"hook": hook, "payload": payload})
        await self._write_line(proc, req)
        raw = await asyncio.wait_for(self._read_line(proc), timeout=30.0)
        return self._rpc.parse_response(raw)

    async def _read_line(self, proc: asyncio.subprocess.Process) -> str | None:
        if proc.stdout is None:
            return None
        line = await proc.stdout.readline()
        return line.decode("utf-8").strip() if line else None

    async def _write_line(self, proc: asyncio.subprocess.Process, data: str) -> None:
        if proc.stdin is None:
            raise RuntimeError("Plugin process has no stdin")
        proc.stdin.write((data + "\n").encode("utf-8"))
        await proc.stdin.drain()
