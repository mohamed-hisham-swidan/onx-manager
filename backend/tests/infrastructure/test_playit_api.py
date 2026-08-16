"""Unit tests for PlayitApiClient (pure infrastructure)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.modules.exposure.infrastructure.playit_api import (
    PlayitAllocationFullError,
    PlayitApiClient,
    PlayitApiError,
    PlayitAuthError,
    PlayitRateLimitError,
    PlayitRundataDto,
    PlayitTunnelDto,
)

pytestmark = pytest.mark.asyncio

SECRET_HEX = "a" * 64


class TestPlayitApiClient:
    async def test_get_rundata_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "status": "ok",
                "data": {
                    "agent_id": "test-agent-123",
                    "agent_type": "self-managed",
                    "account_status": "ready",
                    "tunnels": [
                        {
                            "id": "tun-1",
                            "name": "mcs-panel-abc123",
                            "display_address": "mcs-panel.at.ply.gg:12345",
                            "port_type": "tcp",
                            "local_ip": "127.0.0.1",
                            "local_port": 8000,
                            "is_disabled": False,
                        },
                        {
                            "id": "tun-2",
                            "name": "mcs-server-java",
                            "display_address": "mcs-play.at.ply.gg:25565",
                            "port_type": "tcp",
                            "local_ip": "127.0.0.1",
                            "local_port": 25565,
                            "is_disabled": False,
                        },
                    ],
                },
            }
        )

        mock_client = MagicMock()
        mock_client.request.return_value.__aenter__.return_value = mock_resp

        with patch("app.modules.exposure.infrastructure.playit_api.get_http_client", return_value=mock_client):
            client = PlayitApiClient()
            rundata = await client.get_rundata(SECRET_HEX)

            assert isinstance(rundata, PlayitRundataDto)
            assert rundata.agent_id == "test-agent-123"
            assert len(rundata.tunnels) == 2
            assert rundata.tunnels[0].id == "tun-1"
            assert rundata.tunnels[0].local_port == 8000
            assert rundata.tunnels[0].display_address == "mcs-panel.at.ply.gg:12345"

    async def test_create_tunnel_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "status": "ok",
                "data": {
                    "id": "tun-new-999",
                    "name": "mcs-server-java",
                    "display_address": "crafted-land.ply.gg:30000",
                    "port_type": "tcp",
                    "local_ip": "127.0.0.1",
                    "local_port": 25565,
                },
            }
        )

        mock_client = MagicMock()
        mock_client.request.return_value.__aenter__.return_value = mock_resp

        with patch("app.modules.exposure.infrastructure.playit_api.get_http_client", return_value=mock_client):
            client = PlayitApiClient()
            tunnel = await client.create_tunnel(
                secret=SECRET_HEX,
                name="mcs-server-java",
                local_ip="127.0.0.1",
                local_port=25565,
                port_type="tcp",
                tunnel_type="minecraft-java",
            )

            assert isinstance(tunnel, PlayitTunnelDto)
            assert tunnel.id == "tun-new-999"
            assert tunnel.display_address == "crafted-land.ply.gg:30000"
            assert tunnel.local_port == 25565

    async def test_create_tunnel_allocation_full(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 400
        mock_resp.json = AsyncMock(
            return_value={
                "status": "error",
                "data": {
                    "type": "over_limit",
                    "message": "Maximum free tier tunnel allocation reached",
                },
            }
        )

        mock_client = MagicMock()
        mock_client.request.return_value.__aenter__.return_value = mock_resp

        with patch("app.modules.exposure.infrastructure.playit_api.get_http_client", return_value=mock_client):
            client = PlayitApiClient()
            with pytest.raises(PlayitAllocationFullError):
                await client.create_tunnel(
                    secret=SECRET_HEX,
                    name="mcs-server-java",
                    local_ip="127.0.0.1",
                    local_port=25565,
                )

    async def test_auth_failure_raises_playit_auth_error(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 401
        mock_resp.json = AsyncMock(return_value={"status": "error", "data": "invalid secret key"})

        mock_client = MagicMock()
        mock_client.request.return_value.__aenter__.return_value = mock_resp

        with patch("app.modules.exposure.infrastructure.playit_api.get_http_client", return_value=mock_client):
            client = PlayitApiClient()
            with pytest.raises(PlayitAuthError):
                await client.get_rundata(SECRET_HEX)

    async def test_rate_limit_raises_playit_rate_limit_error(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 429

        mock_client = MagicMock()
        mock_client.request.return_value.__aenter__.return_value = mock_resp

        with patch("app.modules.exposure.infrastructure.playit_api.get_http_client", return_value=mock_client):
            client = PlayitApiClient()
            with pytest.raises(PlayitRateLimitError):
                await client.list_tunnels(SECRET_HEX)

    async def test_delete_tunnel_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"status": "ok", "data": {}})

        mock_client = MagicMock()
        mock_client.request.return_value.__aenter__.return_value = mock_resp

        with patch("app.modules.exposure.infrastructure.playit_api.get_http_client", return_value=mock_client):
            client = PlayitApiClient()
            deleted = await client.delete_tunnel(SECRET_HEX, "tun-123")
            assert deleted is True

    async def test_delete_tunnel_handles_error_gracefully(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_resp.json = AsyncMock(return_value={"status": "error", "data": "not found"})

        mock_client = MagicMock()
        mock_client.request.return_value.__aenter__.return_value = mock_resp

        with patch("app.modules.exposure.infrastructure.playit_api.get_http_client", return_value=mock_client):
            client = PlayitApiClient()
            deleted = await client.delete_tunnel(SECRET_HEX, "tun-nonexistent")
            assert deleted is False
