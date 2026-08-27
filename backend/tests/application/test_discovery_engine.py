from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.server.application.discovery.engine import run_discovery_scan
from app.modules.server.infrastructure.scanner import DiscoveredDirectory

pytestmark = pytest.mark.asyncio


class TestDiscoveryEngine:
    async def test_no_new_servers(self):
        mock_repo = AsyncMock()
        mock_repo.list = AsyncMock(return_value=[])
        mock_event_bus = AsyncMock()
        mock_scanner = AsyncMock()
        mock_scanner.scan = AsyncMock(return_value=[])

        result = await run_discovery_scan(mock_repo, mock_event_bus, mock_scanner)

        assert result == {"discovered": 0, "vanished": 0, "already_known": 0}
        mock_event_bus.publish.assert_not_called()

    async def test_discover_new_server(self):
        mock_repo = AsyncMock()
        mock_repo.list = AsyncMock(return_value=[])
        mock_event_bus = AsyncMock()

        entry = DiscoveredDirectory(
            path="/tmp/servers/new-srv-a1b2c3d4",
            dirname="new-srv-a1b2c3d4",
            detected_type="vanilla",
            has_server_jar=True,
            has_world_dir=True,
            has_server_properties=True,
            has_eula=True,
            size_mb=100.0,
            properties={"server-port": "25565", "level-name": "world"},
        )
        mock_scanner = AsyncMock()
        mock_scanner.scan = AsyncMock(return_value=[entry])

        result = await run_discovery_scan(mock_repo, mock_event_bus, mock_scanner)

        assert result["discovered"] == 1
        assert result["already_known"] == 0
        mock_event_bus.publish.assert_awaited_once()

    async def test_skip_already_known_server(self):
        mock_repo = AsyncMock()
        existing = MagicMock()
        existing.name = "Known Server"
        existing.id = MagicMock()
        existing.id.__str__ = MagicMock(return_value="abc12345")
        existing.deployment = None
        mock_repo.list = AsyncMock(return_value=[existing])
        mock_event_bus = AsyncMock()

        entry = DiscoveredDirectory(
            path="/tmp/servers/known-server-abc12345",
            dirname="known-server-abc12345",
            detected_type="vanilla",
            has_server_jar=True,
            has_world_dir=True,
            has_server_properties=True,
            has_eula=True,
            size_mb=200.0,
            properties={},
        )
        mock_scanner = AsyncMock()
        mock_scanner.scan = AsyncMock(return_value=[entry])

        result = await run_discovery_scan(mock_repo, mock_event_bus, mock_scanner)

        assert result["already_known"] == 1
        assert result["discovered"] == 0
        mock_event_bus.publish.assert_not_called()
