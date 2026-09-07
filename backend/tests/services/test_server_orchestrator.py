from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.server_orchestrator import RestartSaga


@pytest.mark.asyncio
async def test_restart_saga_start_server_forwards_all_configs() -> None:
    mock_saga = MagicMock()
    saga = RestartSaga(mock_saga)

    mock_provider = MagicMock()
    mock_provider.start = AsyncMock()

    mock_server = MagicMock()
    mock_server.id = "srv-123"
    mock_server.name = "My Server"
    mock_server.minecraft_version = "1.21.1"
    mock_server.memory.min_mb = 1024
    mock_server.memory.max_mb = 4096
    mock_server.properties.port.value = 25565
    mock_server.java_args.as_list.return_value = ["-XX:+UseG1GC", "-Dfoo=bar"]
    mock_server.cpu.cores = 4
    mock_server.cpu.affinity = "0-3"
    mock_server.env_vars = {"JAVA_HOME": "/opt/java"}
    mock_server.deployment = MagicMock()
    mock_server.launch_config = MagicMock()

    start_fn = saga._start_server(mock_server, mock_provider)
    await start_fn()

    mock_provider.start.assert_awaited_once()
    args, kwargs = mock_provider.start.call_args
    assert args[0] == "srv-123"
    cfg = args[1]
    assert cfg["name"] == "My Server"
    assert cfg["java_args"] == ["-XX:+UseG1GC", "-Dfoo=bar"]
    assert cfg["cpu_cores"] == 4
    assert cfg["cpu_affinity"] == "0-3"
    assert cfg["env_vars"] == {"JAVA_HOME": "/opt/java"}
    assert kwargs["deployment"] is mock_server.deployment
    assert kwargs["launch_config"] is mock_server.launch_config
