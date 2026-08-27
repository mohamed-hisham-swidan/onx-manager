from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.server.application.discovery.registration import (
    handle_server_discovered,
)
from app.modules.server.domain.events import ServerDiscoveredEvent

pytestmark = pytest.mark.asyncio


class TestRegistrationEngine:
    async def test_register_discovered_server(self):
        mock_repo = AsyncMock()
        mock_repo.save = AsyncMock()
        mock_event_bus = AsyncMock()

        event = ServerDiscoveredEvent(
            path="/tmp/servers/my-srv-a1b2c3d4",
            detected_type="vanilla",
            metadata={
                "dirname": "my-srv-a1b2c3d4",
                "server_port": "25565",
            },
        )

        with patch(
            "app.modules.server.application.discovery.registration.Server.create",
        ) as mock_create:
            mock_server = MagicMock()
            mock_server.id = MagicMock()
            mock_server.id.__str__ = MagicMock(return_value="abc12345")
            mock_create.return_value = mock_server

            result = await handle_server_discovered(event, mock_repo, mock_event_bus)

        assert result == "abc12345"
        mock_repo.save.assert_awaited_once()

    async def test_register_with_error(self):
        mock_repo = AsyncMock()
        mock_repo.save = AsyncMock(side_effect=Exception("DB error"))
        mock_event_bus = AsyncMock()

        event = ServerDiscoveredEvent(
            path="/tmp/servers/bad-srv",
            detected_type="paper",
            metadata={"dirname": "bad-srv"},
        )

        with patch(
            "app.modules.server.application.discovery.registration.Server.create",
        ) as mock_create:
            mock_server = MagicMock()
            mock_server.id = MagicMock()
            mock_server.id.__str__ = MagicMock(return_value="bad12345")
            mock_create.return_value = mock_server

            result = await handle_server_discovered(event, mock_repo, mock_event_bus)

        assert result is None
