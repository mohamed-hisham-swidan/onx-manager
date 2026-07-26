from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def execute_command(command_type: str, payload: dict[str, Any] | None = None) -> Any:
    executor = _CommandExecutor()
    return await executor.execute(command_type, payload)


async def query_data(query_type: str, payload: dict[str, Any] | None = None) -> Any:
    executor = _CommandExecutor()
    return await executor._send_request("query", {"query_type": query_type, "payload": payload})


class _CommandExecutor:
    def __init__(self) -> None:
        self._request_id = 0

    async def execute(self, command_type: str, payload: dict[str, Any] | None = None) -> Any:
        return await self._send_request("command", {"command_type": command_type, "payload": payload})

    async def _send_request(self, method: str, params: dict[str, Any]) -> Any:
        self._request_id += 1
        request = json.dumps({
            "jsonrpc": "2.0",
            "id": f"sdk-{self._request_id}",
            "method": method,
            "params": params,
        })
        import sys

        sys.stdout.write(request + "\n")
        sys.stdout.flush()

        line = sys.stdin.readline()
        if not line:
            raise ConnectionError("No response from host")

        response = json.loads(line.strip())
        if "error" in response:
            err = response["error"]
            raise RuntimeError(f"Host error {err.get('code')}: {err.get('message')}")
        return response.get("result")
