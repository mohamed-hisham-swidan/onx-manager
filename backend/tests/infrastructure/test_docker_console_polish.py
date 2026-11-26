"""Console polish: truthful RCON-disabled error and single-source log streaming."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import ProviderError
from app.modules.server.infrastructure.console_stream import ConsoleStreamManager
from app.modules.server.infrastructure.providers.base import ServerHandle
from app.modules.server.infrastructure.providers.docker import (
    RCON_DISABLED_MESSAGE,
    DockerProvider,
)


def _handle(server_dir: Path) -> ServerHandle:
    return ServerHandle(
        provider="docker",
        server_id="srv-rcon",
        external_id="onx-srv-rcon",
        metadata={"server_dir": str(server_dir)},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "props",
    [
        "enable-rcon=false\nrcon.password=secret\n",
        "enable-rcon=true\nrcon.password=\n",
    ],
)
async def test_execute_command_reports_rcon_disabled(tmp_path: Path, props: str) -> None:
    (tmp_path / "server.properties").write_text(props, encoding="utf-8")
    provider = DockerProvider()
    with pytest.raises(ProviderError) as exc_info:
        await provider.execute_command(_handle(tmp_path), "list")
    assert RCON_DISABLED_MESSAGE in str(exc_info.value)
    assert "still starting up" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_command_enabled_rcon_booting_says_starting(tmp_path: Path) -> None:
    (tmp_path / "server.properties").write_text(
        "enable-rcon=true\nrcon.password=secret\n", encoding="utf-8"
    )
    provider = DockerProvider()
    with (
        patch.object(
            provider,
            "_resolve_rcon_credentials",
            AsyncMock(return_value=("127.0.0.1", 25575, "secret")),
        ),
        patch(
            "app.modules.server.infrastructure.providers.docker.AsyncRCONClient"
        ) as client_cls,
        patch.object(
            provider,
            "status",
            AsyncMock(return_value=__import__(
                "app.modules.server.infrastructure.providers.base",
                fromlist=["ServerRuntimeStatus"],
            ).ServerRuntimeStatus.RUNNING),
        ),
    ):
        client_cls.return_value.connect = AsyncMock(side_effect=ConnectionRefusedError("no"))
        with pytest.raises(ProviderError) as exc_info:
            await provider.execute_command(_handle(tmp_path), "list")
    assert "still starting up" in str(exc_info.value)


@pytest.mark.asyncio
async def test_console_returns_docker_logs_only() -> None:
    provider = DockerProvider()
    with patch.object(
        provider, "_docker_command", AsyncMock(return_value=(0, "a\nb\n"))
    ) as cmd:
        lines = await provider.console(_handle(Path("/nonexistent")), tail=50)
    assert lines == ["a", "b"]
    assert cmd.await_count == 1
    assert cmd.await_args.args[0] == "logs"


@pytest.mark.asyncio
async def test_stopped_server_stream_waits_for_container_not_latest_log() -> None:
    manager = ConsoleStreamManager(broadcast_fn=AsyncMock())
    manager._running = True
    queue: asyncio.Queue[str] = asyncio.Queue()
    resolutions = [("", "file_tail", Path("x")), ("onx-srv", "docker", None)]
    docker_calls: list[tuple[str, str]] = []

    async def fake_resolve(_channel: str):
        return resolutions.pop(0) if len(resolutions) > 1 else resolutions[0]

    async def fake_docker(name: str, _q: asyncio.Queue[str], tail: str = "0") -> None:
        docker_calls.append((name, tail))

    with (
        patch.object(manager, "_resolve_target", fake_resolve),
        patch.object(manager, "_docker_logs_producer", fake_docker),
        patch.object(manager, "_file_tail_producer", AsyncMock()) as file_tail,
    ):
        await manager._await_container_producer("server:srv:console", queue, poll_seconds=0.01)
    assert docker_calls == [("onx-srv", "200")]
    file_tail.assert_not_called()
