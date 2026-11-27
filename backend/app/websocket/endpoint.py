from __future__ import annotations

import contextlib
import logging
from typing import Any

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
_console_stream_manager: Any = None


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
    global _registry, _authenticator, _authorizer, _buffer
    global _rate_limiter, _handler, _event_bus, _console_stream_manager
    _registry = ConnectionRegistry()
    _authenticator = WSAuthenticator()
    _authorizer = ChannelAuthorizer()
    _buffer = OfflineMessageBuffer()
    _rate_limiter = WSRateLimiter()
    _handler = WSConnectionHandler(_registry, _authenticator, _authorizer, _buffer, _rate_limiter)
    _event_bus = event_bus

    from app.modules.server.infrastructure.console_stream import ConsoleStreamManager

    _console_stream_manager = ConsoleStreamManager(broadcast_channel_lines)
    _registry.add_subscription_listener(_console_stream_manager.on_subscription_change)


async def start_websocket_services() -> None:
    """Start MetricsBatcher, MetricsBridgeHandler, EventDispatcher, and ConsoleStreamManager."""
    global _batcher, _bridge, _dispatcher, _console_stream_manager
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
    if _console_stream_manager is not None:
        await _console_stream_manager.start()
    logger.info(
        "WebSocket services started (batcher window=%.2fs, dispatcher subscribed %d types)",
        live.metrics_interval_seconds,
        len(WS_DISPATCH_ALLOWLIST),
    )


async def stop_websocket_services() -> None:
    """Stop MetricsBatcher, EventDispatcher, and ConsoleStreamManager gracefully."""
    global _dispatcher, _console_stream_manager
    if _batcher is not None:
        await _batcher.stop()
    if _dispatcher is not None:
        await _dispatcher.stop()
        _dispatcher = None
    if _console_stream_manager is not None:
        await _console_stream_manager.stop()
    logger.info("WebSocket services stopped")


def get_metrics_batcher() -> MetricsBatcher | None:
    """Return the global active MetricsBatcher instance, if any."""
    return _batcher


def get_console_stream_manager() -> Any:
    """Return the active ConsoleStreamManager instance, if any."""
    return _console_stream_manager


async def broadcast_console_lines(server_id: str, lines: list[str]) -> int:
    """Broadcast console output lines to subscribers on server:<server_id>:console."""
    return await broadcast_channel_lines(f"server:{server_id}:console", lines)


async def broadcast_channel_lines(channel: str, lines: list[str]) -> int:
    """Broadcast console output lines to subscribers on any console channel (server or test)."""
    if _registry is None or not lines:
        return 0
    parts = channel.split(":")
    if len(parts) == 3 and parts[0] == "test" and parts[2] == "console":
        msg = MessageSerializer.test_console_message(parts[1], lines)
    elif len(parts) == 3 and parts[0] == "server" and parts[2] == "console":
        msg = MessageSerializer.console_message(parts[1], lines)
    else:
        from app.websocket.serializers import WSMessage

        msg = WSMessage(type="console", data={"channel": channel, "lines": lines}, channel=channel)
    return await _registry.broadcast(channel, msg.to_json())


async def disconnect_user_sessions(user_id: str, reason: str = "Session invalidated") -> None:
    """Force-close all active WebSocket connections for a user and clear bindings."""
    if _authorizer is not None:
        _authorizer.clear_user(user_id)
    if _registry is None:
        return
    await _registry.clear_user_bindings(user_id)
    entries = await _registry.get_user_connection_entries(user_id)
    for cid, ws in entries:
        with contextlib.suppress(Exception):
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
        await _registry.deregister(cid)
        if _authenticator is not None:
            _authenticator.remove_connection(cid)


async def revalidate_user_sessions(user_id: str) -> None:
    """Recompute live DB context for connected WebSockets and prune revoked channels."""
    if _authorizer is None or _registry is None:
        return
    from app.core.authorization import (
        database_has_users,
        load_user_auth_context,
        load_user_model_with_roles,
    )
    from app.core.persistence.db import database

    if database._session_factory is None:
        return
    try:
        async with database.session_factory() as db:
            user_model = await load_user_model_with_roles(db, user_id)
            if user_model is None:
                if await database_has_users(db):
                    await disconnect_user_sessions(user_id, reason="User account not found")
                return
            if not user_model.is_active:
                await disconnect_user_sessions(user_id, reason="Account disabled")
                return
            live_ctx = await load_user_auth_context(db, user_model)
    except Exception:
        return

    _authorizer.set_user_context(user_id, live_ctx)
    entries = await _registry.get_user_connection_entries(user_id)
    for cid, _ws in entries:
        subs = await _registry.get_subscriptions(cid)
        for ch in subs:
            if not _authorizer.can_subscribe(user_id, ch):
                await _registry.unsubscribe(cid, ch)
                await _registry.unbind_user_channel(user_id, ch)


@router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    token: str = "",
    event_bus: EventBus = Depends(get_event_bus),
) -> None:
    if _handler is None:
        init_websocket(event_bus)

    token = token or ws.query_params.get("token", "")
    live_ctx: dict[str, Any] | None = None
    if not token:
        from app.core.local_auth import resolve_local_auto_auth
        from app.core.persistence.db import database

        local_claims = None
        if database._session_factory is not None:
            client_host = ws.client.host if ws.client else None
            async with database.session_factory() as db:
                local_claims = await resolve_local_auto_auth(client_host, ws.headers, db)
        if local_claims is None:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
            return
        user_id = local_claims["user_id"]
        permissions = set(local_claims.get("permissions", []))
        token = "local_zero_login"
    else:
        try:
            claims = verify_ws_token(token)
            user_id = claims["user_id"]
            permissions = set(claims["permissions"])
        except Exception as e:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(e))
            return

        from app.core.authorization import (
            database_has_users,
            load_user_auth_context,
            load_user_model_with_roles,
        )
        from app.core.persistence.db import database

        if database._session_factory is not None:
            try:
                async with database.session_factory() as db:
                    user_model = await load_user_model_with_roles(db, user_id)
                    if user_model is None:
                        if await database_has_users(db):
                            await ws.close(
                                code=status.WS_1008_POLICY_VIOLATION,
                                reason="User account not found",
                            )
                            return
                        if _authorizer is not None:
                            _authorizer.set_empty_db_user(user_id, True)
                    elif not user_model.is_active:
                        await ws.close(
                            code=status.WS_1008_POLICY_VIOLATION,
                            reason="Account is deactivated",
                        )
                        return
                    else:
                        live_ctx = await load_user_auth_context(db, user_model)
                        permissions = set(live_ctx.get("permissions", []))
            except Exception as exc:
                logger.warning(
                    "WebSocket DB authorization lookup failed for user %s: %s",
                    user_id,
                    exc,
                )
                await ws.close(
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="Authorization check failed",
                )
                return

    await ws.accept()

    handler = _handler
    if handler is not None:
        if _authorizer is not None and live_ctx is not None:
            _authorizer.set_user_context(user_id, live_ctx)
        await handler.handle(ws, token, user_id, permissions)
