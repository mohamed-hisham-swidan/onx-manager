from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.core.event_bus import EventBus
from app.modules.operations.domain.events import (
    OperationStartedEvent,
)
from app.websocket.authorization import ChannelAuthorizer
from app.websocket.buffer import OfflineMessageBuffer
from app.websocket.dispatcher import EventDispatcher
from app.websocket.manager import ConnectionRegistry


@pytest.mark.asyncio
async def test_operation_websocket_authorization():
    authorizer = ChannelAuthorizer()

    # User with server:read can subscribe to specific operation
    authorizer.set_permissions("user_normal", {"server:read"})
    assert authorizer.can_subscribe("user_normal", "operation:op_123") is True
    # But cannot subscribe to operation:* wildcard without admin:full
    assert authorizer.can_subscribe("user_normal", "operation:*") is False

    # Admin user can subscribe to wildcard
    authorizer.set_permissions("user_admin", {"admin:full"})
    assert authorizer.can_subscribe("user_admin", "operation:*") is True
    assert authorizer.can_subscribe("user_admin", "operation:op_123") is True

    # Validate channel format
    assert ChannelAuthorizer.validate_channel("operation:op_123") is True
    assert ChannelAuthorizer.validate_channel("operation:*") is True
    assert ChannelAuthorizer.validate_channel("operation:op:extra:invalid") is False


@pytest.mark.asyncio
async def test_operation_events_dispatching():
    event_bus = EventBus()
    registry = ConnectionRegistry()
    buffer = OfflineMessageBuffer()
    dispatcher = EventDispatcher(registry, buffer, event_bus)

    from app.websocket.dispatcher import WS_DISPATCH_ALLOWLIST

    assert "OperationStartedEvent" in WS_DISPATCH_ALLOWLIST
    assert "OperationStepEvent" in WS_DISPATCH_ALLOWLIST
    assert "OperationCompletedEvent" in WS_DISPATCH_ALLOWLIST

    # Channel resolution
    op_started = OperationStartedEvent(
        operation_id="op_test_1",
        event_seq=1,
        type="RUN_TEST",
        target_type="server",
        target_id="srv_456",
        server_id="srv_456",
    )
    channels = dispatcher._resolve_channels(op_started)
    assert "operation:op_test_1" in channels
    assert "operation:*" in channels
    assert "server:srv_456" in channels
    assert "server:*" in channels

    # Mock connection receiving the message
    mock_ws = AsyncMock()
    await registry.register("conn_1", mock_ws)
    await registry.subscribe("conn_1", "operation:op_test_1")

    await dispatcher.handle(op_started)
    assert mock_ws.send_bytes.called
    sent_payload = json.loads(mock_ws.send_bytes.call_args[0][0].decode("utf-8"))
    assert sent_payload["type"] == "event"
    assert sent_payload["event"]["event_type"] == "OperationStartedEvent"
    assert sent_payload["event"]["operation_id"] == "op_test_1"
    assert sent_payload["event"]["event_seq"] == 1
