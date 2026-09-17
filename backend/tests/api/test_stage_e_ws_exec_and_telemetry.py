from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.persistence.db import database
from app.modules.monitoring.infrastructure.collector import (
    ContainerStats,
    MetricsCollector,
    _parse_size_str_to_mb,
    parse_docker_stats_output,
)

# ---------------------------------------------------------------------------
# Telemetry: docker stats parsing and merging tests
# ---------------------------------------------------------------------------


def test_parse_size_str_to_mb():
    assert _parse_size_str_to_mb("512MiB") == 512.0
    assert _parse_size_str_to_mb("1.5GiB") == 1.5 * 1024.0
    assert _parse_size_str_to_mb("1024KiB") == 1.0
    assert _parse_size_str_to_mb("") == 0.0


def test_parse_docker_stats_output():
    sample_output = "\n".join(
        [
            json.dumps(
                {
                    "Name": "onx-server-s01",
                    "Container": "c01",
                    "CPUPerc": "25.5%",
                    "MemUsage": "1.2GiB / 4GiB",
                    "NetIO": "15MB / 5MB",
                    "BlockIO": "100MB / 50MB",
                }
            ),
            json.dumps(
                {
                    "Name": "onx-test-t01",
                    "Container": "c02",
                    "CPUPerc": "350.0%",  # multi-core burst
                    "MemUsage": "800MiB / 2GiB",
                    "NetIO": "2MB / 1MB",
                    "BlockIO": "10MB / 5MB",
                }
            ),
            "invalid json line",
        ]
    )

    stats = parse_docker_stats_output(sample_output)
    assert "onx-server-s01" in stats
    s01 = stats["onx-server-s01"]
    assert s01.ram_used_mb == 1.2 * 1024.0
    assert s01.cpu_percent <= 100.0  # Normalized/clamped
    assert s01.net_rx_mb == 15.0
    assert s01.net_tx_mb == 5.0
    assert s01.block_read_mb == 100.0

    assert "onx-test-t01" in stats
    t01 = stats["onx-test-t01"]
    assert t01.ram_used_mb == 800.0
    assert t01.cpu_percent <= 100.0  # Clamped ceiling


@pytest.mark.asyncio
async def test_metrics_collector_merges_docker_stats_with_rcon():
    collector = MetricsCollector()
    collector._docker_stats_cache = {
        "onx-server-srv1": ContainerStats(
            name="onx-server-srv1",
            cpu_percent=12.5,
            ram_used_mb=1500.0,
            net_rx_mb=20.0,
            net_tx_mb=10.0,
            block_read_mb=50.0,
            block_write_mb=25.0,
        )
    }

    fake_server = MagicMock()
    fake_server.runtime.pid = 9999
    fake_server.runtime.external_id = "onx-server-srv1"
    fake_server.runtime.host = "127.0.0.1"
    fake_server.deployment = None

    with (
        patch(
            "app.modules.server.infrastructure.repository.SQLServerRepository.get",
            new_callable=AsyncMock,
            return_value=fake_server,
        ),
        patch.object(
            collector,
            "_rcon_clients",
            {},
        ),
        patch(
            "app.modules.monitoring.infrastructure.repository.SQLMetricRepository.record",
            new_callable=AsyncMock,
        ),
    ):
        metrics = await collector.collect("srv1")
        # CPU and RAM come from docker stats
        assert metrics.ram_used_mb == 1500.0
        assert metrics.cpu_percent == 12.5
        assert metrics.net_rx_mb == 20.0
        assert metrics.block_read_mb == 50.0


@pytest.mark.asyncio
async def test_metrics_collector_test_run_sweep_and_missing_container_resilience():
    event_bus = MagicMock()
    event_bus.publish = AsyncMock()
    collector = MetricsCollector(event_bus=event_bus)
    collector._docker_stats_cache = {
        "onx-test-run-1": ContainerStats(
            name="onx-test-run-1",
            cpu_percent=45.0,
            ram_used_mb=2048.0,
        )
    }

    # 1. Existing test run
    m1 = await collector.collect_test_run("run-1")
    assert m1 is not None
    assert m1.server_id == "test:run-1"
    assert m1.ram_used_mb == 2048.0
    assert m1.cpu_percent == 45.0
    assert m1.tps is None
    assert m1.players == 0
    event_bus.publish.assert_called_once()

    # 2. Missing/destroyed test run (e.g. torn down mid-sweep)
    m2 = await collector.collect_test_run("run-disappeared")
    assert m2 is None  # Handled gracefully, no exception


# ---------------------------------------------------------------------------
# WebSocket exec_input & permission enforcement tests
# ---------------------------------------------------------------------------


class _MockWS:
    def __init__(self) -> None:
        self.sent_bytes: list[bytes] = []

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)


@pytest.fixture
def ws_handler():
    from app.websocket.authentication import WSAuthenticator
    from app.websocket.authorization import ChannelAuthorizer
    from app.websocket.buffer import OfflineMessageBuffer
    from app.websocket.handlers import WSConnectionHandler
    from app.websocket.manager import ConnectionRegistry
    from app.websocket.rate_limiter import WSRateLimiter

    registry = ConnectionRegistry()
    authenticator = WSAuthenticator()
    authorizer = ChannelAuthorizer()
    buffer = OfflineMessageBuffer()
    rate_limiter = WSRateLimiter()
    return WSConnectionHandler(registry, authenticator, authorizer, buffer, rate_limiter)


@pytest.mark.asyncio
async def test_ws_exec_input_live_server_permission_granted(ws_handler) -> None:
    ws_handler._authorizer.set_permissions("u_admin", {"server.s01.console"})
    ws = _MockWS()

    fake_server = MagicMock()
    fake_server.runtime.provider = "docker"
    fake_server.runtime.external_id = "onx-server-s01"

    fake_provider = MagicMock()
    fake_provider.write_exec_input = AsyncMock(return_value="Executed command successfully")

    mock_session = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_repo = MagicMock()
    mock_repo.get = AsyncMock(return_value=fake_server)

    with (
        patch.object(database, "_session_factory", mock_session_factory),
        patch(
            "app.modules.server.infrastructure.repository.SQLServerRepository",
            return_value=mock_repo,
        ),
        patch(
            "app.modules.server.infrastructure.providers.provider_factory.get",
            return_value=fake_provider,
        ),
    ):
        await ws_handler._handle_message(
            ws,
            "c_1",
            "u_admin",
            {
                "type": "exec_input",
                "target_type": "server",
                "target_id": "s01",
                "input": "say Hello",
            },
        )

        assert len(ws.sent_bytes) == 1
        resp = json.loads(ws.sent_bytes[0].decode("utf-8"))
        assert resp["type"] == "exec_result"
        assert resp["target_id"] == "s01"
        assert resp["output"] == "Executed command successfully"
        fake_provider.write_exec_input.assert_called_once()


@pytest.mark.asyncio
async def test_ws_exec_input_live_server_permission_denied(ws_handler) -> None:
    ws_handler._authorizer.set_permissions("u_viewer", {"server:read"})
    ws = _MockWS()

    fake_server = MagicMock()
    fake_server.runtime.provider = "docker"
    fake_server.runtime.external_id = "onx-server-s01"

    mock_session = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_repo = MagicMock()
    mock_repo.get = AsyncMock(return_value=fake_server)

    with (
        patch.object(database, "_session_factory", mock_session_factory),
        patch(
            "app.modules.server.infrastructure.repository.SQLServerRepository",
            return_value=mock_repo,
        ),
    ):
        await ws_handler._handle_message(
            ws,
            "c_2",
            "u_viewer",
            {
                "type": "exec_input",
                "target_type": "server",
                "target_id": "s01",
                "input": "stop",
            },
        )

        assert len(ws.sent_bytes) == 1
        resp = json.loads(ws.sent_bytes[0].decode("utf-8"))
        assert resp["type"] == "error"
        assert resp["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_ws_exec_input_test_container_authorized_and_dispatched(ws_handler) -> None:
    ws_handler._authorizer.set_permissions("u_tester", {"server:test:execute"})
    ws = _MockWS()

    fake_test_run = MagicMock()
    fake_test_run.id = "tr-100"
    fake_test_run.server_id = "srv-parent"

    fake_provider = MagicMock()
    fake_provider.write_exec_input = AsyncMock(return_value="[Test Server] Bot command executed")

    async def fake_execute(_stmt):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = fake_test_run
        return mock_result

    mock_session = AsyncMock()
    mock_session.execute = fake_execute
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(database, "_session_factory", mock_session_factory),
        patch(
            "app.modules.server.infrastructure.providers.provider_factory.get",
            return_value=fake_provider,
        ),
    ):
        await ws_handler._handle_message(
            ws,
            "c_3",
            "u_tester",
            {
                "type": "exec_input",
                "target_type": "test",
                "target_id": "tr-100",
                "input": "time set day",
            },
        )

        assert len(ws.sent_bytes) == 1
        resp = json.loads(ws.sent_bytes[0].decode("utf-8"))
        assert resp["type"] == "exec_result"
        assert resp["target_id"] == "tr-100"
        assert resp["target_type"] == "test"
        assert resp["output"] == "[Test Server] Bot command executed"
        fake_provider.write_exec_input.assert_called_once()
        handle_arg = fake_provider.write_exec_input.call_args[0][0]
        assert handle_arg.external_id == "onx-test-tr-100"


@pytest.mark.asyncio
async def test_ws_exec_input_test_container_permission_denied(ws_handler) -> None:
    ws_handler._authorizer.set_permissions("u_other", {"server.other_server.console"})
    ws = _MockWS()

    fake_test_run = MagicMock()
    fake_test_run.id = "tr-200"
    fake_test_run.server_id = "srv-target"

    async def fake_execute(_stmt):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = fake_test_run
        return mock_result

    mock_session = AsyncMock()
    mock_session.execute = fake_execute
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch.object(database, "_session_factory", mock_session_factory):
        await ws_handler._handle_message(
            ws,
            "c_4",
            "u_other",
            {
                "type": "exec_input",
                "target_type": "test",
                "target_id": "tr-200",
                "input": "kill @e",
            },
        )

        assert len(ws.sent_bytes) == 1
        resp = json.loads(ws.sent_bytes[0].decode("utf-8"))
        assert resp["type"] == "error"
        assert resp["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_ws_exec_resize_ack(ws_handler) -> None:
    ws_handler._authorizer.set_permissions("u_dev", {"server:read"})
    ws = _MockWS()

    await ws_handler._handle_message(
        ws,
        "c_5",
        "u_dev",
        {
            "type": "exec_resize",
            "cols": 120,
            "rows": 40,
        },
    )

    assert len(ws.sent_bytes) == 1
    resp = json.loads(ws.sent_bytes[0].decode("utf-8"))
    assert resp["type"] == "exec_resize_ack"
    assert resp["cols"] == 120
    assert resp["rows"] == 40
