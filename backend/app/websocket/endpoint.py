from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, WebSocket, status

from app.api.deps import get_event_bus
from app.core.event_bus import DomainEvent, EventBus, EventHandler
from app.core.settings_store import get_live_settings
from app.modules.auth.infrastructure.jwt import verify_ws_token
from app.websocket.authentication import WSAuthenticator
from app.websocket.authorization import ChannelAuthorizer
from app.websocket.buffer import OfflineMessageBuffer
from app.websocket.dispatcher import WS_DISPATCH_ALLOWLIST, EventDispatcher, MetricsBatcher
from app.websocket.handlers import WSConnectionHandler
from app.websocket.manager import ConnectionRegistry
from app.websocket.rate_limiter import WSRateLimiter
from app.websocket.serializers import MessageSerializer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

_registry: ConnectionRegistry | None = None
_authenticator: WSAuthenticator | None = None
_authorizer: ChannelAuthorizer | None = None
_buffer: OfflineMessageBuffer | None = None
_rate_limiter: WSRateLimiter | None = None
_handler: WSConnectionHandler | None = None
_event_bus: EventBus | None = None
_batcher: MetricsBatcher | None = None
_bridge: MetricsBridgeHandler | None = None
_dispatcher: EventDispatcher | None = None


class MetricsBridgeHandler(EventHandler):
    """Subscribes to MetricCollectedEvent and feeds samples into MetricsBatcher."""

    def __init__(self, batcher: MetricsBatcher) -> None:
        self._batcher = batcher

    async def handle(self, event: DomainEvent) -> None:
        await self._batcher.add_sample(
            event.server_id,  # type: ignore[attr-defined]
            {
                "ts": event.timestamp,
                "tps": event.tps,  # type: ignore[attr-defined]
                "players": event.players,  # type: ignore[attr-defined]
                "ram_mb": event.ram_mb,  # type: ignore[attr-defined]
                "cpu": event.cpu,  # type: ignore[attr-defined]
            },
        )


def init_websocket(event_bus: EventBus) -> None:
    global _registry, _authenticator, _authorizer, _buffer, _rate_limiter, _handler, _event_bus
    _registry = ConnectionRegistry()
    _authenticator = WSAuthenticator()
    _authorizer = ChannelAuthorizer()
    _buffer = OfflineMessageBuffer()
    _rate_limiter = WSRateLimiter()
    _handler = WSConnectionHandler(_registry, _authenticator, _authorizer, _buffer, _rate_limiter)
    _event_bus = event_bus


async def start_websocket_services() -> None:
    """Start MetricsBatcher, MetricsBridgeHandler, and EventDispatcher."""
    global _batcher, _bridge, _dispatcher
    if _registry is None or _event_bus is None or _buffer is None:
        logger.warning("start_websocket_services called before init_websocket")
        return
    # Decision 5: read the persisted metrics_interval_seconds at boot so that
    # the batcher window matches the scheduler's interval from the first frame.
    live = get_live_settings()
    _batcher = MetricsBatcher(_registry, window_seconds=live.metrics_interval_seconds)
    _bridge = MetricsBridgeHandler(_batcher)
    _event_bus.subscribe("MetricCollectedEvent", _bridge)
    await _batcher.start()
    # Decision 1: instantiate and start EventDispatcher with the 31-type allowlist.
    _dispatcher = EventDispatcher(_registry, _buffer, _event_bus)
    await _dispatcher.start(event_types=WS_DISPATCH_ALLOWLIST)
    logger.info(
        "WebSocket services started (batcher window=%.2fs, dispatcher subscribed %d types)",
        live.metrics_interval_seconds,
        len(WS_DISPATCH_ALLOWLIST),
    )


async def stop_websocket_services() -> None:
    """Stop MetricsBatcher and EventDispatcher gracefully."""
    global _dispatcher
    if _batcher is not None:
        await _batcher.stop()
    if _dispatcher is not None:
        await _dispatcher.stop()
        _dispatcher = None
    logger.info("WebSocket services stopped")


def get_metrics_batcher() -> MetricsBatcher | None:
    """Return the global active MetricsBatcher instance, if any."""
    return _batcher


async def broadcast_console_lines(server_id: str, lines: list[str]) -> int:
    """Broadcast console output lines to subscribers on server:<server_id>:console."""
    if _registry is None or not lines:
        return 0
    channel = f"server:{server_id}:console"
    msg = MessageSerializer.console_message(server_id, lines)
    return await _registry.broadcast(channel, msg.to_json())


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
