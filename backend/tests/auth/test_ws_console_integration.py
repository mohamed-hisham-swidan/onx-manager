from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import deps
from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.query_bus import QueryBus
from app.main import create_app
from app.modules.auth.infrastructure.jwt import create_access_token
from app.websocket import endpoint as ws_endpoint


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


@pytest.fixture
def ws_client() -> TestClient:
    app = create_app()
    app.router.lifespan_context = _noop_lifespan

    event_bus = EventBus()
    deps.init_buses(CommandBus(), QueryBus(), event_bus)
    ws_endpoint.init_websocket(event_bus)

    with TestClient(app) as client:
        yield client


@pytest.mark.asyncio
async def test_ws_console_viewer_can_subscribe(ws_client: TestClient) -> None:
    token = create_access_token(user_id="u_viewer", permissions=["server:read"])
    with ws_client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_text('{"type": "subscribe", "channels": ["server:s01:console"]}')

        subs = ws_client.portal.call(ws_endpoint._registry.get_by_channel, "server:s01:console")
        assert len(subs) == 1, "viewer with server:read must be subscribed to console channel"


@pytest.mark.asyncio
async def test_ws_console_writer_without_read_denied(ws_client: TestClient) -> None:
    token = create_access_token(user_id="u_writer", permissions=["server:write"])
    with ws_client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_text('{"type": "subscribe", "channels": ["server:s01:console"]}')

        msg = ws.receive_bytes()
        assert b"PERMISSION_DENIED" in msg

        subs = ws_client.portal.call(ws_endpoint._registry.get_by_channel, "server:s01:console")
        assert len(subs) == 0, "writer without server:read must not be subscribed"


@pytest.mark.asyncio
async def test_ws_console_unrelated_permission_denied(ws_client: TestClient) -> None:
    token = create_access_token(user_id="u_backup", permissions=["backup:read"])
    with ws_client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_text('{"type": "subscribe", "channels": ["server:s01:console"]}')

        msg = ws.receive_bytes()
        assert b"PERMISSION_DENIED" in msg

        subs = ws_client.portal.call(ws_endpoint._registry.get_by_channel, "server:s01:console")
        assert len(subs) == 0


@pytest.mark.asyncio
async def test_ws_console_missing_token_rejected(ws_client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with ws_client.websocket_connect("/ws") as ws:
            ws.receive_bytes()
    assert exc_info.value.code == 1008
