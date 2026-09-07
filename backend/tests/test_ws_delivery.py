"""
SPEC-WS-DELIVERY-001 — Backend Acceptance Tests T-WS-01 through T-WS-14
Pre-fix failure reasons are stated in each test docstring.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import patch

import pytest

from app.core.event_bus import DomainEvent, EventBus, EventHandler, Subscription
from app.websocket.authorization import ChannelAuthorizer
from app.websocket.buffer import BufferedMessage, OfflineMessageBuffer
from app.websocket.dispatcher import WS_DISPATCH_ALLOWLIST, EventDispatcher
from app.websocket.manager import ConnectionRegistry

# ---------------------------------------------------------------------------
# Shared helpers / stubs
# ---------------------------------------------------------------------------


class _MockWS:
    def __init__(self) -> None:
        self.sent_bytes: list[bytes] = []

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        pass

    @property
    def query_params(self) -> dict:
        return {}

    @property
    def headers(self) -> dict:
        return {}


class _ServerStartedEvent(DomainEvent):
    event_type: str = "ServerStartedEvent"
    server_id: str = "srv-test"


class _ServerCrashedEvent(DomainEvent):
    event_type: str = "ServerCrashedEvent"
    server_id: str = "srv-test"


class _UserCreatedEvent(DomainEvent):
    event_type: str = "UserCreatedEvent"


class _MetricCollectedEvent(DomainEvent):
    event_type: str = "MetricCollectedEvent"
    server_id: str = "srv-test"
    tps: float = 20.0
    players: int = 5
    ram_mb: float = 2048.0
    cpu: float = 45.0


def _frames(ws: _MockWS) -> list[dict[str, Any]]:
    return [json.loads(b) for b in ws.sent_bytes]


# ---------------------------------------------------------------------------
# T-WS-01 — EventDispatcher is subscribed after start_websocket_services()
# Pre-fix failure: start_websocket_services() never instantiated EventDispatcher.
# ---------------------------------------------------------------------------
class TestTWS01:
    @pytest.mark.asyncio
    async def test_dispatcher_subscribed_after_start(self) -> None:
        from app.websocket.endpoint import (
            init_websocket,
            start_websocket_services,
            stop_websocket_services,
        )

        eb = EventBus()
        init_websocket(eb)
        await start_websocket_services()
        try:
            assert "ServerStartedEvent" in eb._subscribers
            subscribed = set(eb._subscribers.keys())
            overlap = subscribed & set(WS_DISPATCH_ALLOWLIST)
            assert len(overlap) == len(WS_DISPATCH_ALLOWLIST), (
                f"Missing from bus: {set(WS_DISPATCH_ALLOWLIST) - overlap}"
            )
        finally:
            await stop_websocket_services()


# ---------------------------------------------------------------------------
# T-WS-02 — ServerStartedEvent reaches server:* subscriber
# Pre-fix failure: no dispatcher subscribed → EventBus returned early.
# ---------------------------------------------------------------------------
class TestTWS02:
    @pytest.mark.asyncio
    async def test_server_started_delivered(self) -> None:
        eb = EventBus()
        reg = ConnectionRegistry()
        buf = OfflineMessageBuffer()
        disp = EventDispatcher(reg, buf, eb)
        await disp.start(event_types=["ServerStartedEvent"])

        ws = _MockWS()
        await reg.register("c1", ws)
        await reg.subscribe("c1", "server:*")

        await eb.publish(_ServerStartedEvent())
        await asyncio.sleep(0.05)
        await disp.stop()

        event_frames = [f for f in _frames(ws) if f.get("type") == "event"]
        assert any(
            f.get("event", {}).get("event_type") == "ServerStartedEvent" for f in event_frames
        ), f"Expected ServerStartedEvent; got {_frames(ws)}"


# ---------------------------------------------------------------------------
# T-WS-03 — ServerCrashedEvent reaches server:* subscriber
# Pre-fix failure: same as T-WS-02.
# ---------------------------------------------------------------------------
class TestTWS03:
    @pytest.mark.asyncio
    async def test_server_crashed_delivered(self) -> None:
        eb = EventBus()
        reg = ConnectionRegistry()
        buf = OfflineMessageBuffer()
        disp = EventDispatcher(reg, buf, eb)
        await disp.start(event_types=["ServerCrashedEvent"])

        ws = _MockWS()
        await reg.register("c1", ws)
        await reg.subscribe("c1", "server:*")

        await eb.publish(_ServerCrashedEvent())
        await asyncio.sleep(0.05)
        await disp.stop()

        event_frames = [f for f in _frames(ws) if f.get("type") == "event"]
        assert any(
            f.get("event", {}).get("event_type") == "ServerCrashedEvent" for f in event_frames
        ), f"Expected ServerCrashedEvent; got {_frames(ws)}"


# ---------------------------------------------------------------------------
# T-WS-04 — Crash handler is subscribed (structural wiring assertion)
# Pre-fix failure: HandleServerCrashHandler never subscribed anywhere.
# ---------------------------------------------------------------------------
class TestTWS04:
    @pytest.mark.asyncio
    async def test_crash_handler_subscribed(self) -> None:
        from app.registration import _register_event_handlers

        eb = EventBus()
        _register_event_handlers(eb)
        assert "ServerCrashedEvent" in eb._subscribers, (
            "HandleServerCrashHandler must be subscribed to ServerCrashedEvent"
        )
        # Confirm the subscriber is HandleServerCrashHandler
        from app.modules.health.application.event_handlers.server_crashed_handler import (
            HandleServerCrashHandler,
        )

        handlers_for_crash = [sub.handler for sub in eb._subscribers["ServerCrashedEvent"]]
        assert any(isinstance(h, HandleServerCrashHandler) for h in handlers_for_crash)


# ---------------------------------------------------------------------------
# T-WS-05 — All crash-chain subscriptions present
# Pre-fix failure: registration.py had no _register_event_handlers block.
# ---------------------------------------------------------------------------
class TestTWS05:
    @pytest.mark.asyncio
    async def test_crash_chain_subscriptions(self) -> None:
        from app.registration import _register_event_handlers

        eb = EventBus()
        _register_event_handlers(eb)

        for et in (
            "ServerCrashedEvent",
            "CrashClassifiedEvent",
            "RuntimeHealthSignalEvent",
            "IntegrityCheckFailedEvent",
        ):
            assert et in eb._subscribers, f"Missing subscription: {et}"


# ---------------------------------------------------------------------------
# T-WS-06 — Offline buffer: deregister preserves bindings; buffer is fed; drain works
# Pre-fix failure: _find_disconnected_user_ids iterated _user_connections (cleared on
# deregister) → offline user invisible → buffer.add unreachable.
# ---------------------------------------------------------------------------
class TestTWS06:
    @pytest.mark.asyncio
    async def test_offline_buffer_filled_and_drained(self) -> None:
        eb = EventBus()
        reg = ConnectionRegistry()
        buf = OfflineMessageBuffer()
        disp = EventDispatcher(reg, buf, eb)
        await disp.start(event_types=["ServerStartedEvent"])

        ws1 = _MockWS()
        await reg.register("c1", ws1)
        await reg.link_user("alice", "c1")
        await reg.subscribe("c1", "server:*")
        await reg.bind_user_channel("alice", "server:*")

        # Disconnect
        await reg.deregister("c1")

        assert "server:*" in reg._user_channel_bindings.get("alice", set()), (
            "_user_channel_bindings must survive deregister()"
        )
        assert "alice" not in reg._user_connections

        # Publish while offline
        await eb.publish(_ServerStartedEvent())
        await asyncio.sleep(0.05)

        buffered = buf.get_pending("alice")
        assert len(buffered) == 1, f"Expected 1 buffered event; got {len(buffered)}"

        # Reconnect + drain
        ws2 = _MockWS()
        await reg.register("c2", ws2)
        await reg.link_user("alice", "c2")
        from app.websocket.serializers import MessageSerializer

        events = [m.data for m in buffered]
        raw = MessageSerializer.state_sync_message(events).to_json()
        await ws2.send_bytes(raw)
        buf.clear("alice")

        assert any(f.get("type") == "state_sync" for f in _frames(ws2))
        assert buf.get_pending("alice") == []

        await disp.stop()


# ---------------------------------------------------------------------------
# T-WS-07 — Stop clears subscriptions; restart does not leak
# Pre-fix failure: EventDispatcher never started/stopped from endpoint.py.
# ---------------------------------------------------------------------------
class TestTWS07:
    @pytest.mark.asyncio
    async def test_stop_clears_and_restart_no_leak(self) -> None:
        from app.websocket.endpoint import (
            init_websocket,
            start_websocket_services,
            stop_websocket_services,
        )

        eb = EventBus()
        init_websocket(eb)

        await start_websocket_services()
        await stop_websocket_services()

        for et in WS_DISPATCH_ALLOWLIST:
            active = [s for s in eb._subscribers.get(et, []) if not s.cancelled]
            assert not active, f"Active subscription for {et} after stop()"

        # Restart — must not double subscriptions
        await start_websocket_services()
        try:
            active = [s for s in eb._subscribers.get("ServerStartedEvent", []) if not s.cancelled]
            assert len(active) == 1, f"Expected 1 after restart, got {len(active)}"
        finally:
            await stop_websocket_services()


# ---------------------------------------------------------------------------
# T-WS-08 — MetricCollectedEvent excluded from allowlist → no event frame
# Pre-fix failure: allowlist didn't exist; exclusion was implicit/absent.
# ---------------------------------------------------------------------------
class TestTWS08:
    def test_metric_events_excluded_from_allowlist(self) -> None:
        assert "MetricCollectedEvent" not in WS_DISPATCH_ALLOWLIST
        assert "MetricRecordedEvent" not in WS_DISPATCH_ALLOWLIST

    @pytest.mark.asyncio
    async def test_metric_event_produces_no_event_frame(self) -> None:
        eb = EventBus()
        reg = ConnectionRegistry()
        buf = OfflineMessageBuffer()
        disp = EventDispatcher(reg, buf, eb)
        await disp.start(event_types=WS_DISPATCH_ALLOWLIST)

        ws = _MockWS()
        await reg.register("c1", ws)
        await reg.subscribe("c1", "server:*")

        await eb.publish(_MetricCollectedEvent())
        await asyncio.sleep(0.05)
        await disp.stop()

        event_frames = [f for f in _frames(ws) if f.get("type") == "event"]
        assert not event_frames, (
            f"MetricCollectedEvent must not produce event frame; got {event_frames}"
        )


# ---------------------------------------------------------------------------
# T-WS-09 — Auth events never reach server:* (privacy guard)
# Pre-fix failure: allowlist didn't exist.
# ---------------------------------------------------------------------------
class TestTWS09:
    def test_auth_events_not_in_allowlist(self) -> None:
        for et in ("UserCreatedEvent", "UserLoggedInEvent", "ApiKeyCreatedEvent"):
            assert et not in WS_DISPATCH_ALLOWLIST, f"{et} must NOT be in allowlist"

    @pytest.mark.asyncio
    async def test_user_created_not_delivered(self) -> None:
        eb = EventBus()
        reg = ConnectionRegistry()
        buf = OfflineMessageBuffer()
        disp = EventDispatcher(reg, buf, eb)
        await disp.start(event_types=WS_DISPATCH_ALLOWLIST)

        ws = _MockWS()
        await reg.register("c1", ws)
        await reg.subscribe("c1", "server:*")

        await eb.publish(_UserCreatedEvent())
        await asyncio.sleep(0.05)
        await disp.stop()

        assert not _frames(ws), f"UserCreatedEvent must not be delivered; got {_frames(ws)}"


# ---------------------------------------------------------------------------
# T-WS-10 — Permission downgrade: buffered events filtered on drain
# Pre-fix failure: _send_pending_events sent all events without permission check.
# ---------------------------------------------------------------------------
class TestTWS10:
    @pytest.mark.asyncio
    async def test_downgraded_token_filtered_on_drain(self) -> None:
        from app.websocket.authentication import WSAuthenticator
        from app.websocket.handlers import WSConnectionHandler
        from app.websocket.rate_limiter import WSRateLimiter

        reg = ConnectionRegistry()
        auth = WSAuthenticator()
        authz = ChannelAuthorizer()
        buf = OfflineMessageBuffer()
        handler = WSConnectionHandler(reg, auth, authz, buf, WSRateLimiter())

        buf.add(
            "bob",
            BufferedMessage(
                data={"event_type": "ServerStartedEvent", "server_id": "srv-x"},
                timestamp=time.time(),
                channels=["server:*"],
            ),
        )

        ws = _MockWS()
        await reg.register("c-new", ws)
        await reg.link_user("bob", "c-new")
        authz.set_permissions("bob", set())  # no server:read

        await handler._send_pending_events("c-new", "bob")

        assert buf.get_pending("bob") == [], "Buffer must be cleared"
        sync_frames = [f for f in _frames(ws) if f.get("type") == "state_sync"]
        assert not sync_frames, f"No state_sync expected after downgrade; got {sync_frames}"


# ---------------------------------------------------------------------------
# T-WS-13 — MetricsBatcher boot window from persisted metrics_interval_seconds
# Pre-fix failure: endpoint.py hardcoded window_seconds via default param (0.2).
# ---------------------------------------------------------------------------
class TestTWS13:
    @pytest.mark.asyncio
    async def test_batcher_window_from_live_settings(self) -> None:
        import app.websocket.endpoint as _ep
        from app.core.settings_store import LiveSettings
        from app.websocket.endpoint import (
            init_websocket,
            start_websocket_services,
            stop_websocket_services,
        )

        eb = EventBus()
        init_websocket(eb)

        custom = LiveSettings(metrics_interval_seconds=1.5)
        with patch("app.websocket.endpoint.get_live_settings", return_value=custom):
            await start_websocket_services()
            try:
                assert _ep._batcher is not None
                assert _ep._batcher._window_seconds == 1.5, (
                    f"Expected 1.5 from live settings, got {_ep._batcher._window_seconds}"
                )
            finally:
                await stop_websocket_services()


# ---------------------------------------------------------------------------
# T-WS-14 — Per-subscriber timeout override (Decision 2a)
# Pre-fix failure: Subscription had no timeout field; subscribe() had no timeout param;
# _dispatch_with_retry hardcoded self._subscriber_timeout (10 s).
# ---------------------------------------------------------------------------
class TestTWS14:
    def test_subscription_has_timeout_field(self) -> None:
        import dataclasses

        fields = {f.name: f for f in dataclasses.fields(Subscription)}
        assert "timeout" in fields, "Subscription must have 'timeout' field"
        assert fields["timeout"].default is None

    def test_crash_handler_has_60s_override(self) -> None:
        from app.registration import _register_event_handlers

        eb = EventBus()
        _register_event_handlers(eb)

        crash_subs = eb._subscribers.get("ServerCrashedEvent", [])
        assert crash_subs
        assert crash_subs[0].timeout == 60.0, f"Expected 60 s override, got {crash_subs[0].timeout}"

    def test_health_handler_uses_global_default(self) -> None:
        from app.registration import _register_event_handlers

        eb = EventBus()
        _register_event_handlers(eb)

        for et in ("CrashClassifiedEvent", "RuntimeHealthSignalEvent", "IntegrityCheckFailedEvent"):
            subs = eb._subscribers.get(et, [])
            assert subs, f"No subscription for {et}"
            assert subs[0].timeout is None, (
                f"HealthSignalHandler must use global default for {et}, got {subs[0].timeout}"
            )

    def test_global_timeout_unchanged(self) -> None:
        eb = EventBus()
        assert eb._subscriber_timeout == 10.0

    @pytest.mark.asyncio
    async def test_per_sub_override_honored_over_global(self) -> None:
        """
        Fast handler: 0.1 s override, sleeps 0.3 s → times out → dead-lettered.
        Slow handler: no override (global=0.5 s), sleeps 0.3 s → completes.
        """
        eb = EventBus()
        eb.retry_attempts = 1
        eb._subscriber_timeout = 0.5

        fast_done: list[bool] = []
        slow_done: list[bool] = []

        class _Fast(EventHandler):
            async def handle(self, _event: DomainEvent) -> None:
                await asyncio.sleep(0.3)
                fast_done.append(True)

        class _Slow(EventHandler):
            async def handle(self, _event: DomainEvent) -> None:
                await asyncio.sleep(0.3)
                slow_done.append(True)

        eb.subscribe("TWSTimeout", _Fast(), timeout=0.1)
        eb.subscribe("TWSTimeout", _Slow())

        await eb.publish(DomainEvent(event_type="TWSTimeout"))

        assert not fast_done, "Fast handler must have timed out under 0.1 s override"
        assert slow_done, "Slow handler must complete within 0.5 s global"
        assert eb.dead_letter_count >= 1


# ---------------------------------------------------------------------------
# F080 — WebSocket refresh_token validation
# ---------------------------------------------------------------------------
class TestWSRefreshTokenValidation:
    @pytest.mark.asyncio
    async def test_refresh_token_missing_token(self) -> None:
        from app.websocket.authentication import WSAuthenticator
        from app.websocket.handlers import WSConnectionHandler
        from app.websocket.rate_limiter import WSRateLimiter

        reg = ConnectionRegistry()
        auth = WSAuthenticator()
        authz = ChannelAuthorizer()
        buf = OfflineMessageBuffer()
        handler = WSConnectionHandler(reg, auth, authz, buf, WSRateLimiter())

        ws = _MockWS()
        await reg.register("c1", ws)
        auth.register_connection("c1", "user-1", "old-token", time.time() + 300)

        await handler._handle_message(ws, "c1", "user-1", {"type": "refresh_token", "token": ""})

        frames = _frames(ws)
        assert len(frames) == 1
        assert frames[0]["type"] == "error"
        assert frames[0]["code"] == "INVALID_PAYLOAD"

    @pytest.mark.asyncio
    async def test_refresh_token_invalid_signature(self) -> None:
        from app.websocket.authentication import WSAuthenticator
        from app.websocket.handlers import WSConnectionHandler
        from app.websocket.rate_limiter import WSRateLimiter

        reg = ConnectionRegistry()
        auth = WSAuthenticator()
        authz = ChannelAuthorizer()
        buf = OfflineMessageBuffer()
        handler = WSConnectionHandler(reg, auth, authz, buf, WSRateLimiter())

        ws = _MockWS()
        await reg.register("c1", ws)
        auth.register_connection("c1", "user-1", "old-token", time.time() + 300)

        await handler._handle_message(
            ws, "c1", "user-1", {"type": "refresh_token", "token": "bad.jwt.token"}
        )

        frames = _frames(ws)
        assert len(frames) == 1
        assert frames[0]["type"] == "error"
        assert frames[0]["code"] == "INVALID_TOKEN"

    @pytest.mark.asyncio
    async def test_refresh_token_expired(self) -> None:
        from app.modules.auth.infrastructure.jwt import create_access_token
        from app.websocket.authentication import WSAuthenticator
        from app.websocket.handlers import WSConnectionHandler
        from app.websocket.rate_limiter import WSRateLimiter

        reg = ConnectionRegistry()
        auth = WSAuthenticator()
        authz = ChannelAuthorizer()
        buf = OfflineMessageBuffer()
        handler = WSConnectionHandler(reg, auth, authz, buf, WSRateLimiter())

        ws = _MockWS()
        await reg.register("c1", ws)
        auth.register_connection("c1", "user-1", "old-token", time.time() + 300)

        expired_token = create_access_token("user-1", ttl_seconds=-100)
        await handler._handle_message(
            ws, "c1", "user-1", {"type": "refresh_token", "token": expired_token}
        )

        frames = _frames(ws)
        assert len(frames) == 1
        assert frames[0]["type"] == "error"
        assert frames[0]["code"] == "INVALID_TOKEN"

    @pytest.mark.asyncio
    async def test_refresh_token_subject_mismatch(self) -> None:
        from app.modules.auth.infrastructure.jwt import create_access_token
        from app.websocket.authentication import WSAuthenticator
        from app.websocket.handlers import WSConnectionHandler
        from app.websocket.rate_limiter import WSRateLimiter

        reg = ConnectionRegistry()
        auth = WSAuthenticator()
        authz = ChannelAuthorizer()
        buf = OfflineMessageBuffer()
        handler = WSConnectionHandler(reg, auth, authz, buf, WSRateLimiter())

        ws = _MockWS()
        await reg.register("c1", ws)
        auth.register_connection("c1", "user-1", "old-token", time.time() + 300)

        other_user_token = create_access_token("user-other", ttl_seconds=600)
        await handler._handle_message(
            ws, "c1", "user-1", {"type": "refresh_token", "token": other_user_token}
        )

        frames = _frames(ws)
        assert len(frames) == 1
        assert frames[0]["type"] == "error"
        assert frames[0]["code"] == "FORBIDDEN"

    @pytest.mark.asyncio
    async def test_refresh_token_success_updates_authenticator_and_permissions(self) -> None:
        from app.modules.auth.infrastructure.jwt import create_access_token
        from app.websocket.authentication import WSAuthenticator
        from app.websocket.handlers import WSConnectionHandler
        from app.websocket.rate_limiter import WSRateLimiter

        reg = ConnectionRegistry()
        auth = WSAuthenticator()
        authz = ChannelAuthorizer()
        buf = OfflineMessageBuffer()
        handler = WSConnectionHandler(reg, auth, authz, buf, WSRateLimiter())

        ws = _MockWS()
        await reg.register("c1", ws)
        auth.register_connection("c1", "user-1", "old-token", time.time() + 300)
        authz.set_permissions("user-1", set())

        assert authz.can_subscribe("user-1", "server:s01") is False

        valid_token = create_access_token(
            "user-1",
            permissions=["server:read"],
            ttl_seconds=1800,
        )
        await handler._handle_message(
            ws, "c1", "user-1", {"type": "refresh_token", "token": valid_token}
        )

        # No error frames sent
        frames = _frames(ws)
        assert len(frames) == 0

        # Authenticator updated
        conn = auth.get_connection("c1")
        assert conn is not None
        assert conn.token == valid_token
        assert conn.token_expires_at > time.time() + 1700

        # Permissions updated in authorizer
        assert authz.can_subscribe("user-1", "server:s01") is True


class TestBatch4EProvisionChannelAuthorization:
    """F096: ChannelAuthorizer validates and authorizes provision channels."""

    def test_validate_channel_accepts_provision(self) -> None:
        assert ChannelAuthorizer.validate_channel("provision:s01") is True
        assert ChannelAuthorizer.validate_channel("provision:*") is True
        assert ChannelAuthorizer.validate_channel("server:s01:console") is True
        assert ChannelAuthorizer.validate_channel("provision:s01:invalid") is False

    def test_can_subscribe_provision_requires_server_read(self) -> None:
        authz = ChannelAuthorizer()
        authz.set_permissions("user-1", {"server:read"})
        authz.set_permissions("user-2", {"user:read"})
        authz.set_permissions("admin-user", {"admin:full"})

        assert authz.can_subscribe("user-1", "provision:srv-1") is True
        assert authz.can_subscribe("user-1", "provision:*") is True
        assert authz.can_subscribe("user-2", "provision:srv-1") is False
        assert authz.can_subscribe("admin-user", "provision:srv-1") is True

