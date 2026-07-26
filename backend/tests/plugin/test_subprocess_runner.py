from __future__ import annotations

import asyncio
import json

import pytest

from app.modules.plugin.infrastructure.runner.base import PluginRunner
from app.modules.plugin.infrastructure.runner.subprocess import (
    JsonRpcClient,
    JsonRpcError,
    SubprocessPluginRunner,
)


class TestJsonRpcClient:
    def test_build_request(self) -> None:
        client = JsonRpcClient()
        req = client.build_request("ping")
        data = json.loads(req)
        assert data["jsonrpc"] == "2.0"
        assert data["method"] == "ping"
        assert data["id"] == 1

    def test_request_id_increments(self) -> None:
        client = JsonRpcClient()
        r1 = json.loads(client.build_request("ping"))
        r2 = json.loads(client.build_request("ping"))
        assert r2["id"] == r1["id"] + 1

    def test_parse_response(self) -> None:
        client = JsonRpcClient()
        result = client.parse_response('{"jsonrpc": "2.0", "id": 1, "result": "pong"}')
        assert result == "pong"

    def test_parse_error(self) -> None:
        client = JsonRpcClient()
        with pytest.raises(JsonRpcError) as exc:
            client.parse_response('{"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}')
        assert exc.value.code == -32601
        assert "Method not found" in str(exc.value)

    def test_parse_response_with_params(self) -> None:
        client = JsonRpcClient()
        result = client.parse_response('{"jsonrpc": "2.0", "id": 2, "result": {"status": "ok"}}')
        assert result["status"] == "ok"


class TestSubprocessPluginRunner:
    @pytest.mark.asyncio
    async def test_health_returns_false_for_unknown(self) -> None:
        runner = SubprocessPluginRunner()
        healthy = await runner.health("nonexistent")
        assert not healthy

    @pytest.mark.asyncio
    async def test_stop_noop_for_unknown(self) -> None:
        runner = SubprocessPluginRunner()
        await runner.stop("nonexistent")
        assert True

    @pytest.mark.asyncio
    async def test_start_raises_for_missing_entrypoint(self) -> None:
        runner = SubprocessPluginRunner()
        with pytest.raises(FileNotFoundError):
            await runner.start("p1", "/tmp/nonexistent", {"entry_point": "main.py"})

    @pytest.mark.asyncio
    async def test_restart_does_not_raise(self) -> None:
        runner = SubprocessPluginRunner()
        await runner.restart("p1")
        assert True


class TestPluginRunnerABC:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            PluginRunner()  # type: ignore[abstract]
