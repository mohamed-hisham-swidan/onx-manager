from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from app.api.deps import get_event_bus
from app.core.event_bus import EventBus
from app.modules.auth.infrastructure.jwt import verify_ws_token
from app.websocket.authentication import WSAuthenticator
from app.websocket.authorization import ChannelAuthorizer
from app.websocket.buffer import OfflineMessageBuffer
from app.websocket.handlers import WSConnectionHandler
from app.websocket.manager import ConnectionRegistry
from app.websocket.rate_limiter import WSRateLimiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

_registry: ConnectionRegistry | None = None
_authenticator: WSAuthenticator | None = None
_authorizer: ChannelAuthorizer | None = None
_buffer: OfflineMessageBuffer | None = None
_rate_limiter: WSRateLimiter | None = None
_handler: WSConnectionHandler | None = None
_event_bus: EventBus | None = None


def init_websocket(event_bus: EventBus) -> None:
    global _registry, _authenticator, _authorizer, _buffer, _rate_limiter, _handler, _event_bus
    _registry = ConnectionRegistry()
    _authenticator = WSAuthenticator()
    _authorizer = ChannelAuthorizer()
    _buffer = OfflineMessageBuffer()
    _rate_limiter = WSRateLimiter()
    _handler = WSConnectionHandler(_registry, _authenticator, _authorizer, _buffer, _rate_limiter)
    _event_bus = event_bus


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    token: str = "",
    event_bus: EventBus = Depends(get_event_bus),
) -> None:
    if _handler is None:
        init_websocket(event_bus)

    token = token or ws.query_params.get("token", "")
    if not token:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
        return

    try:
        claims = verify_ws_token(token)
        user_id = claims["user_id"]
        permissions = claims["permissions"]
    except Exception as e:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(e))
        return

    await ws.accept()

    handler = _handler
    if handler is not None:
        await handler.handle(ws, token, user_id, permissions)
