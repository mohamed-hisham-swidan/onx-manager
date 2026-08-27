from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from typing import Any

from plugins.sdk.commands import _CommandExecutor
from plugins.sdk.config import Config
from plugins.sdk.events import _EventBus
from plugins.sdk.http import HttpClient
from plugins.sdk.storage import Storage

logger = logging.getLogger(__name__)


class BasePlugin:
    def __init__(self, plugin_id: str, plugin_dir: str) -> None:
        self._plugin_id = plugin_id
        self._plugin_dir = plugin_dir
        self._events = _EventBus()
        self._commands = _CommandExecutor()
        self._config = Config(plugin_dir)
        self._storage = Storage(plugin_dir)
        self._http = HttpClient()
        self._running = True

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    @property
    def plugin_dir(self) -> str:
        return self._plugin_dir

    @property
    def config(self) -> Config:
        return self._config

    @property
    def storage(self) -> Storage:
        return self._storage

    @property
    def http(self) -> HttpClient:
        return self._http

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        self._events.subscribe(event, handler)

    async def execute_command(
        self, command_type: str, payload: dict[str, Any] | None = None
    ) -> Any:
        return await self._commands.execute(command_type, payload)

    async def run(self) -> None:
        from plugins.sdk.events import _stdin_listener

        await self.on_load()

        stdin_listener = _stdin_listener(sys.stdin, self._handle_message)
        await stdin_listener

    async def on_load(self) -> None:
        pass

    async def on_unload(self) -> None:
        pass

    async def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)

            if msg.get("method") == "ping":
                self._send_response(msg.get("id"), True)

            elif msg.get("method") == "shutdown":
                self._running = False
                await self.on_unload()
                self._send_response(msg.get("id"), "ok")
                sys.exit(0)

            elif msg.get("method") == "hook":
                hook_name = msg.get("params", {}).get("hook", "")
                payload = msg.get("params", {}).get("payload", {})
                result = await self._events.dispatch(hook_name, payload)
                self._send_response(msg.get("id"), result)

            else:
                self._send_error(msg.get("id"), -32601, f"Method not found: {msg.get('method')}")

        except Exception as e:
            self._send_error(None, -32603, str(e))

    def _send_response(self, msg_id: int | str | None, result: Any) -> None:
        response = json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result})
        sys.stdout.write(response + "\n")
        sys.stdout.flush()

    def _send_error(self, msg_id: int | str | None, code: int, message: str) -> None:
        response = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": code, "message": message},
            }
        )
        sys.stdout.write(response + "\n")
        sys.stdout.flush()
