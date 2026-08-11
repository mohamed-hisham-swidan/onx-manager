from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from fastapi import WebSocket

from app.core.event_bus import DomainEvent, EventBus
from app.websocket.authentication import WSAuthenticator
from app.websocket.authorization import ChannelAuthorizer
from app.websocket.buffer import BufferedMessage, OfflineMessageBuffer
from app.websocket.dispatcher import EventDispatcher, MetricsBatcher
from app.websocket.manager import ConnectionRegistry
from app.websocket.rate_limiter import WSRateLimiter
from app.websocket.serializers import MAX_MESSAGE_SIZE, MessageSerializer, WSMessage
from pydantic import Field


class _ServerEvent(DomainEvent):
    event_type: str = "ServerStarted"
    server_id: str = ""


class _BackupEvent(DomainEvent):
    event_type: str = "BackupCompleted"
    server_id: str = ""


class _PluginEvent(DomainEvent):
    event_type: str = "PluginInstalled"
    server_id: str = ""


class _MetricsEvent(DomainEvent):
    event_type: str = "MetricsCollected"
    server_id: str = ""


class TestMessageSerializer:
    def test_ws_message_to_dict(self) -> None:
        msg = WSMessage("event", {"event": {"event_type": "TestEvent"}}, channel="server:test")
        d = msg.to_dict()
        assert d["type"] == "event"
        assert d["event"]["event_type"] == "TestEvent"

    def test_ws_message_to_json(self) -> None:
        msg = WSMessage("pong")
        raw = msg.to_json()
        assert isinstance(raw, bytes)
        assert b"pong" in raw

    def test_message_too_large(self) -> None:
        large_data = {"data": "x" * MAX_MESSAGE_SIZE}
        msg = WSMessage("event", large_data)
        with pytest.raises(ValueError, match="exceeds maximum size"):
            msg.to_json()

    def test_serialize_deserialize_roundtrip(self) -> None:
        original = WSMessage("subscribe", {"channels": ["server:*"]})
        raw = MessageSerializer.serialize(original)
        parsed = MessageSerializer.deserialize(raw)
        assert parsed["type"] == "subscribe"
        assert parsed["channels"] == ["server:*"]

    def test_deserialize_oversized(self) -> None:
        with pytest.raises(ValueError, match="exceeds maximum size"):
            MessageSerializer.deserialize("x" * (MAX_MESSAGE_SIZE + 1))

    def test_deserialize_bytes(self) -> None:
        raw = b'{"type": "ping"}'
        parsed = MessageSerializer.deserialize(raw)
        assert parsed["type"] == "ping"

    def test_event_to_message(self) -> None:
        event = _ServerEvent(server_id="s01")
        msg = MessageSerializer.event_to_message(event)
        assert msg.type == "event"
        assert msg.data["event"]["event_type"] == "ServerStarted"

    def test_state_message(self) -> None:
        msg = MessageSerializer.state_message("s01", {"status": "running"})
        assert msg.type == "state"
        assert msg.data["server_id"] == "s01"
        assert msg.data["status"]["status"] == "running"

    def test_metrics_message(self) -> None:
        msg = MessageSerializer.metrics_message("s01", 20.0, 5, 2048)
        assert msg.type == "metrics"
        assert msg.data["tps"] == 20.0

    def test_metrics_batch_message(self) -> None:
        samples = [{"ts": time.time(), "tps": 19.5, "players": 3}]
        msg = MessageSerializer.metrics_batch_message("s01", samples)
        assert msg.type == "metrics_batch"
        assert len(msg.data["samples"]) == 1

    def test_state_sync_message(self) -> None:
        events = [{"event_type": "ServerStarted"}]
        msg = MessageSerializer.state_sync_message(events)
        assert msg.type == "state_sync"
        assert msg.data["events"] == events

    def test_error_message(self) -> None:
        msg = MessageSerializer.error_message("NOT_FOUND", "Server not found")
        assert msg.type == "error"
        assert msg.data["code"] == "NOT_FOUND"

    def test_auth_expired_message(self) -> None:
        msg = MessageSerializer.auth_expired_message()
        assert msg.type == "auth_expired"

    def test_pong_message(self) -> None:
        msg = MessageSerializer.pong_message()
        assert msg.type == "pong"


class TestConnectionRegistry:
    @pytest.mark.asyncio
    async def test_register_and_get(self) -> None:
        reg = ConnectionRegistry()
        mock_ws = _MockWebSocket()
        await reg.register("conn1", mock_ws)
        retrieved = await reg.get("conn1")
        assert retrieved is mock_ws

    @pytest.mark.asyncio
    async def test_deregister(self) -> None:
        reg = ConnectionRegistry()
        mock_ws = _MockWebSocket()
        await reg.register("conn1", mock_ws)
        await reg.deregister("conn1")
        assert await reg.get("conn1") is None

    @pytest.mark.asyncio
    async def test_link_user(self) -> None:
        reg = ConnectionRegistry()
        mock_ws = _MockWebSocket()
        await reg.register("conn1", mock_ws)
        await reg.link_user("user1", "conn1")
        results = await reg.get_by_user("user1")
        assert mock_ws in results

    @pytest.mark.asyncio
    async def test_subscribe_and_broadcast(self) -> None:
        reg = ConnectionRegistry()
        mock_ws = _MockWebSocket()
        await reg.register("conn1", mock_ws)
        await reg.subscribe("conn1", "server:s01")
        sent = await reg.broadcast("server:s01", b"hello")
        assert sent == 1
        assert mock_ws.sent_bytes == [b"hello"]

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        reg = ConnectionRegistry()
        mock_ws = _MockWebSocket()
        await reg.register("conn1", mock_ws)
        await reg.subscribe("conn1", "server:s01")
        await reg.unsubscribe("conn1", "server:s01")
        sent = await reg.broadcast("server:s01", b"hello")
        assert sent == 0

    @pytest.mark.asyncio
    async def test_get_subscriptions(self) -> None:
        reg = ConnectionRegistry()
        mock_ws = _MockWebSocket()
        await reg.register("conn1", mock_ws)
        await reg.subscribe("conn1", "server:s01")
        await reg.subscribe("conn1", "backup:*")
        subs = await reg.get_subscriptions("conn1")
        assert subs == {"server:s01", "backup:*"}

    @pytest.mark.asyncio
    async def test_get_by_channel(self) -> None:
        reg = ConnectionRegistry()
        ws1 = _MockWebSocket()
        ws2 = _MockWebSocket()
        await reg.register("c1", ws1)
        await reg.register("c2", ws2)
        await reg.subscribe("c1", "server:s01")
        await reg.subscribe("c2", "server:s01")
        results = await reg.get_by_channel("server:s01")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_active_connections(self) -> None:
        reg = ConnectionRegistry()
        assert reg.active_connections == 0
        await reg.register("c1", _MockWebSocket())
        assert reg.active_connections == 1


class TestWSAuthenticator:
    def test_register_and_get_connection(self) -> None:
        auth = WSAuthenticator()
        info = auth.register_connection("conn1", "user1", "token123", time.time() + 3600)
        assert info.connection_id == "conn1"
        assert info.user_id == "user1"
        retrieved = auth.get_connection("conn1")
        assert retrieved is info

    def test_remove_connection(self) -> None:
        auth = WSAuthenticator()
        auth.register_connection("conn1", "user1", "token123", time.time() + 3600)
        auth.remove_connection("conn1")
        assert auth.get_connection("conn1") is None

    def test_token_expired(self) -> None:
        auth = WSAuthenticator()
        auth.register_connection("conn1", "user1", "token123", time.time() - 10)
        assert auth.is_token_expired("conn1")

    def test_token_not_expired(self) -> None:
        auth = WSAuthenticator()
        auth.register_connection("conn1", "user1", "token123", time.time() + 3600)
        assert not auth.is_token_expired("conn1")

    def test_refresh_token(self) -> None:
        auth = WSAuthenticator()
        auth.register_connection("conn1", "user1", "token123", time.time() + 10)
        new_expiry = time.time() + 7200
        assert auth.refresh_token("conn1", "new-token", new_expiry)
        info = auth.get_connection("conn1")
        assert info is not None
        assert info.token == "new-token"

    def test_refresh_nonexistent(self) -> None:
        auth = WSAuthenticator()
        assert not auth.refresh_token("nonexistent", "t", 0.0)

    def test_update_activity(self) -> None:
        auth = WSAuthenticator()
        auth.register_connection("conn1", "user1", "t", time.time() + 3600)
        old = auth.get_connection("conn1")
        assert old is not None
        old.last_activity = time.time() - 10
        auth.update_activity("conn1")
        assert auth.get_connection("conn1") is not None

    def test_is_idle(self) -> None:
        auth = WSAuthenticator()
        auth.register_connection("conn1", "user1", "t", time.time() + 3600)
        info = auth.get_connection("conn1")
        assert info is not None
        info.last_activity = time.time() - 100
        assert auth.is_idle("conn1")

    def test_idle_timeout(self) -> None:
        assert WSAuthenticator.IDLE_TIMEOUT == 90.0

    def test_active_connections_count(self) -> None:
        auth = WSAuthenticator()
        assert auth.active_connections == 0
        auth.register_connection("c1", "u1", "t", time.time() + 3600)
        assert auth.active_connections == 1


class TestChannelAuthorizer:
    def test_set_and_get_permissions(self) -> None:
        ca = ChannelAuthorizer()
        perms = {"server:read", "server:write"}
        ca.set_permissions("user1", perms)
        assert ca.get_permissions("user1") == perms

    def test_empty_permissions(self) -> None:
        ca = ChannelAuthorizer()
        assert ca.get_permissions("nobody") == set()

    def test_can_subscribe_wildcard_with_permissions(self) -> None:
        ca = ChannelAuthorizer()
        ca.set_permissions("user1", {"server:read", "server:write"})
        assert ca.can_subscribe("user1", "server:*")

    def test_can_subscribe_wildcard_without_permissions(self) -> None:
        ca = ChannelAuthorizer()
        ca.set_permissions("user1", {"backup:read"})
        assert not ca.can_subscribe("user1", "server:*")

    def test_can_subscribe_specific_server(self) -> None:
        ca = ChannelAuthorizer()
        ca.set_permissions("user1", {"server:read"})
        assert ca.can_subscribe("user1", "server:s01")

    def test_can_subscribe_no_permissions(self) -> None:
        ca = ChannelAuthorizer()
        assert not ca.can_subscribe("nobody", "server:*")

    def test_singular_permission_grants_where_plural_failed(self) -> None:
        ca = ChannelAuthorizer()
        ca.set_permissions("user1", {"server:read"})
        assert ca.can_subscribe("user1", "server:s01")

    def test_admin_full_bypasses_channel_requirements(self) -> None:
        ca = ChannelAuthorizer()
        ca.set_permissions("user1", {"admin:full"})
        assert ca.can_subscribe("user1", "server:*")
        assert ca.can_subscribe("user1", "server:s01")
        assert ca.can_subscribe("user1", "server:s01:console")
        assert ca.can_subscribe("user1", "backup:*")
        assert ca.can_subscribe("user1", "plugin:*")
        assert ca.can_subscribe("user1", "monitoring:s01")
        assert ca.can_subscribe("user1", "metrics:*")
        assert ca.can_subscribe("user1", "auth:*")
        assert ca.can_subscribe("user1", "user:u01")

    def test_missing_required_permission_denied(self) -> None:
        ca = ChannelAuthorizer()
        ca.set_permissions("user1", {"backup:create"})
        assert not ca.can_subscribe("user1", "server:s01")
        assert not ca.can_subscribe("user1", "plugin:*")
        assert not ca.can_subscribe("user1", "user:u01")

    def test_console_channel_requires_read_permission(self) -> None:
        # Console streaming is view-level (server.{id}.view); write permission is NOT required
        ca = ChannelAuthorizer()
        ca.set_permissions("user1", {"server:read"})
        assert ca.can_subscribe("user1", "server:s01:console")
        ca.set_permissions("user1", {"server:write"})
        assert not ca.can_subscribe("user1", "server:s01:console")
        ca.set_permissions("user1", set())
        assert not ca.can_subscribe("user1", "server:s01:console")

    def test_pattern_requires_existing_singular_permission(self) -> None:
        ca = ChannelAuthorizer()
        ca.set_permissions("user1", {"monitoring:read"})
        assert not ca.can_subscribe("user1", "monitoring:s01")

    def test_is_wildcard(self) -> None:
        assert ChannelAuthorizer.is_wildcard("server:*")
        assert ChannelAuthorizer.is_wildcard("backup:*")
        assert not ChannelAuthorizer.is_wildcard("server:s01")

    def test_validate_channel(self) -> None:
        assert ChannelAuthorizer.validate_channel("server:s01")
        assert ChannelAuthorizer.validate_channel("monitoring:*")
        assert ChannelAuthorizer.validate_channel("server:s01:console")
        assert not ChannelAuthorizer.validate_channel("invalid")
        assert not ChannelAuthorizer.validate_channel("")
        assert not ChannelAuthorizer.validate_channel("unknown:test")
        assert not ChannelAuthorizer.validate_channel("a:b:c")
        assert not ChannelAuthorizer.validate_channel("monitoring:s01:other")
        assert not ChannelAuthorizer.validate_channel("server:s01:console:extra")

    def test_channel_pattern_match(self) -> None:
        assert ChannelAuthorizer._match_pattern("server:s01", "server:{server_id}")
        assert not ChannelAuthorizer._match_pattern("server:s01", "server:s02")
        assert ChannelAuthorizer._match_pattern("monitoring:s01", "monitoring:{server_id}")
        assert ChannelAuthorizer._match_pattern("server:s01:console", "server:{server_id}:console")
        assert not ChannelAuthorizer._match_pattern("server:s01", "server:{server_id}:console")

    def test_max_channels_constant(self) -> None:
        from app.websocket.authorization import MAX_CHANNELS_PER_CONNECTION
        assert MAX_CHANNELS_PER_CONNECTION == 50


class TestWSRateLimiter:
    def test_check_allows_within_limit(self) -> None:
        limiter = WSRateLimiter(max_messages=10, window_seconds=60)
        for _ in range(10):
            assert limiter.check("conn1")

    def test_check_blocks_over_limit(self) -> None:
        limiter = WSRateLimiter(max_messages=3, window_seconds=60)
        for _ in range(3):
            assert limiter.check("conn1")
        assert not limiter.check("conn1")

    def test_separate_connections_independent(self) -> None:
        limiter = WSRateLimiter(max_messages=1, window_seconds=60)
        assert not limiter.check("conn1") is False
        limiter._buckets.clear()
        assert limiter.check("conn2")

    def test_properties(self) -> None:
        limiter = WSRateLimiter(max_messages=50, window_seconds=1)
        assert limiter.max_messages == 50
        assert limiter.window_seconds == 1


class TestOfflineMessageBuffer:
    def test_add_and_get_pending(self) -> None:
        buf = OfflineMessageBuffer()
        msg = BufferedMessage({"type": "event"}, time.time(), ["server:*"])
        buf.add("user1", msg)
        pending = buf.get_pending("user1")
        assert len(pending) == 1
        assert pending[0].data["type"] == "event"

    def test_clear(self) -> None:
        buf = OfflineMessageBuffer()
        buf.add("user1", BufferedMessage({"type": "event"}, time.time(), ["server:*"]))
        buf.clear("user1")
        assert buf.get_pending("user1") == []

    def test_max_events_enforced(self) -> None:
        buf = OfflineMessageBuffer(max_events=3)
        for _ in range(5):
            buf.add("user1", BufferedMessage({"type": "event"}, time.time(), ["server:*"]))
        assert buf.total_buffered("user1") == 3

    def test_ttl_expiry(self) -> None:
        buf = OfflineMessageBuffer(ttl_seconds=0)
        buf.add("user1", BufferedMessage({"type": "event"}, time.time() - 10, ["server:*"]))
        buf._last_cleanup = 0.0
        pending = buf.get_pending("user1")
        assert len(pending) == 0

    def test_total_buffered_all(self) -> None:
        buf = OfflineMessageBuffer()
        buf.add("u1", BufferedMessage({"type": "a"}, time.time(), ["s:*"]))
        buf.add("u2", BufferedMessage({"type": "b"}, time.time(), ["s:*"]))
        assert buf.total_buffered() == 2

    def test_total_buffered_per_user(self) -> None:
        buf = OfflineMessageBuffer()
        buf.add("u1", BufferedMessage({"type": "a"}, time.time(), ["s:*"]))
        buf.add("u1", BufferedMessage({"type": "b"}, time.time(), ["s:*"]))
        assert buf.total_buffered("u1") == 2
        assert buf.total_buffered("u2") == 0

    def test_properties(self) -> None:
        buf = OfflineMessageBuffer(max_events=50, ttl_seconds=120)
        assert buf.max_events == 50
        assert buf.ttl_seconds == 120


class TestEventDispatcher:
    @pytest.mark.asyncio
    async def test_dispatcher_start_stop(self) -> None:
        eb = EventBus()
        reg = ConnectionRegistry()
        buf = OfflineMessageBuffer()
        dispatcher = EventDispatcher(reg, buf, eb)
        await dispatcher.start(event_types=["ServerStarted"])
        assert len(dispatcher._subscriptions) == 1
        await dispatcher.stop()
        assert len(dispatcher._subscriptions) == 0

    @pytest.mark.asyncio
    async def test_dispatch_sends_to_subscribed_channel(self) -> None:
        eb = EventBus()
        reg = ConnectionRegistry()
        buf = OfflineMessageBuffer()
        dispatcher = EventDispatcher(reg, buf, eb)

        mock_ws = _MockWebSocket()
        await reg.register("c1", mock_ws)
        await reg.subscribe("c1", "server:s01")

        await dispatcher.start(event_types=["ServerStarted"])
        event = _ServerEvent(server_id="s01")
        await eb.publish(event)
        await asyncio.sleep(0.05)

        await dispatcher.stop()
        assert len(mock_ws.sent_bytes) > 0

    def test_resolve_channels_with_server_id(self) -> None:
        eb = EventBus()
        reg = ConnectionRegistry()
        buf = OfflineMessageBuffer()
        dispatcher = EventDispatcher(reg, buf, eb)

        event = _ServerEvent(server_id="s01")
        channels = dispatcher._resolve_channels(event)
        assert "server:s01" in channels
        assert "server:*" in channels

    def test_resolve_channels_backup(self) -> None:
        eb = EventBus()
        reg = ConnectionRegistry()
        buf = OfflineMessageBuffer()
        dispatcher = EventDispatcher(reg, buf, eb)

        event = _BackupEvent(server_id="s01")
        channels = dispatcher._resolve_channels(event)
        assert "backup:*" in channels

    def test_resolve_channels_plugin(self) -> None:
        eb = EventBus()
        reg = ConnectionRegistry()
        buf = OfflineMessageBuffer()
        dispatcher = EventDispatcher(reg, buf, eb)

        event = _PluginEvent(server_id="s01")
        channels = dispatcher._resolve_channels(event)
        assert "plugin:*" in channels

    def test_resolve_channels_default(self) -> None:
        eb = EventBus()
        reg = ConnectionRegistry()
        buf = OfflineMessageBuffer()
        dispatcher = EventDispatcher(reg, buf, eb)

        event = DomainEvent(event_type="UnknownEvent")
        channels = dispatcher._resolve_channels(event)
        assert "server:*" in channels


class TestMetricsBatcher:
    @pytest.mark.asyncio
    async def test_add_sample_and_flush(self) -> None:
        reg = ConnectionRegistry()
        batcher = MetricsBatcher(reg, window_seconds=0.1)
        mock_ws = _MockWebSocket()
        await reg.register("c1", mock_ws)
        await reg.subscribe("c1", "metrics:s01")

        await batcher.add_sample("s01", {"ts": time.time(), "tps": 20.0, "players": 5})
        await batcher._flush()
        assert len(mock_ws.sent_bytes) > 0

    @pytest.mark.asyncio
    async def test_batch_loop_start_stop(self) -> None:
        reg = ConnectionRegistry()
        batcher = MetricsBatcher(reg)
        await batcher.start()
        assert batcher._running
        await batcher.stop()
        assert not batcher._running


class TestEndpoint:
    @pytest.mark.asyncio
    async def test_websocket_router_registered(self) -> None:
        from app.websocket.endpoint import router
        routes = [r.path for r in router.routes]
        assert "/ws" in routes


class _MockWebSocket:
    def __init__(self) -> None:
        self.sent_bytes: list[bytes] = []
        self.sent_text: list[str] = []
        self.closed = False

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)

    async def send_text(self, data: str) -> None:
        self.sent_text.append(data)

    async def receive_text(self) -> str:
        raise _WebSocketDisconnected()

    async def receive_bytes(self) -> bytes:
        raise _WebSocketDisconnected()

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True

    @property
    def headers(self) -> dict:
        return {}

    @property
    def query_params(self) -> dict:
        return {}


class _WebSocketDisconnected(Exception):
    pass


class TestMetricsBridgeHandler:
    @pytest.mark.asyncio
    async def test_bridge_maps_event_fields_correctly(self) -> None:
        from app.modules.monitoring.infrastructure.collector import MetricCollectedEvent
        from app.websocket.endpoint import MetricsBridgeHandler

        reg = ConnectionRegistry()
        batcher = MetricsBatcher(reg)
        bridge = MetricsBridgeHandler(batcher)

        event = MetricCollectedEvent(
            server_id="s01",
            tps=19.5,
            players=3,
            ram_mb=2048.0,
            cpu=45.0,
        )
        await bridge.handle(event)

        assert "s01" in batcher._samples
        assert len(batcher._samples["s01"]) == 1
        sample = batcher._samples["s01"][0]
        assert sample["tps"] == 19.5
        assert sample["players"] == 3
        assert sample["ram_mb"] == 2048.0
        assert sample["cpu"] == 45.0
        assert "ts" in sample
        assert isinstance(sample["ts"], float)

    @pytest.mark.asyncio
    async def test_bridge_integration_event_bus_to_broadcast(self) -> None:
        from app.modules.monitoring.infrastructure.collector import MetricCollectedEvent
        from app.websocket.endpoint import MetricsBridgeHandler

        eb = EventBus()
        reg = ConnectionRegistry()
        batcher = MetricsBatcher(reg)
        bridge = MetricsBridgeHandler(batcher)

        eb.subscribe("MetricCollectedEvent", bridge)

        mock_ws = _MockWebSocket()
        await reg.register("c1", mock_ws)
        await reg.subscribe("c1", "metrics:s01")

        event = MetricCollectedEvent(
            server_id="s01",
            tps=20.0,
            players=5,
            ram_mb=3072.0,
            cpu=60.0,
        )
        await eb.publish(event)
        await asyncio.sleep(0.05)
        await batcher._flush()

        assert len(mock_ws.sent_bytes) > 0
        import json
        payload = json.loads(mock_ws.sent_bytes[0])
        assert payload["type"] == "metrics_batch"
        assert payload["server_id"] == "s01"
        assert len(payload["samples"]) == 1
        assert payload["samples"][0]["tps"] == 20.0
        assert payload["samples"][0]["ram_mb"] == 3072.0

