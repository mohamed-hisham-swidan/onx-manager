from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ConnectionRegistry:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._user_connections: dict[str, set[str]] = defaultdict(set)
        self._channel_connections: dict[str, set[str]] = defaultdict(set)
        self._connection_channels: dict[str, set[str]] = defaultdict(set)
        # Persistent channel bindings keyed by user_id.  Unlike the live maps
        # above, these survive disconnect so that offline users remain visible
        # to _find_disconnected_user_ids for offline buffering (Decision 3).
        self._user_channel_bindings: dict[str, set[str]] = defaultdict(set)
        self._subscription_listeners: list[Any] = []
        self._lock = asyncio.Lock()

    def add_subscription_listener(self, listener: Any) -> None:
        """Register a callback (channel: str, count: int) invoked on subscriber count changes."""
        self._subscription_listeners.append(listener)

    async def get_channel_subscriber_count(self, channel: str) -> int:
        async with self._lock:
            return len(self._channel_connections.get(channel, set()))

    async def register(self, connection_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._connections[connection_id] = ws

    async def deregister(self, connection_id: str) -> None:
        affected: list[tuple[str, int]] = []
        async with self._lock:
            self._connections.pop(connection_id, None)
            channels = self._connection_channels.pop(connection_id, set())
            for ch in channels:
                self._channel_connections[ch].discard(connection_id)
                count = len(self._channel_connections[ch])
                if not self._channel_connections[ch]:
                    del self._channel_connections[ch]
                affected.append((ch, count))
            for user_id, conns in list(self._user_connections.items()):
                conns.discard(connection_id)
                if not conns:
                    del self._user_connections[user_id]
            # NOTE: _user_channel_bindings is intentionally NOT cleared here.
            # Bindings persist so that the dispatcher can buffer events for
            # offline users.  Eviction is handled by EventDispatcher.

        for ch, count in affected:
            for listener in self._subscription_listeners:
                try:
                    res = listener(ch, count)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass

    async def get(self, connection_id: str) -> WebSocket | None:
        async with self._lock:
            return self._connections.get(connection_id)

    async def get_by_user(self, user_id: str) -> list[WebSocket]:
        async with self._lock:
            conn_ids = self._user_connections.get(user_id, set())
            return [self._connections[cid] for cid in conn_ids if cid in self._connections]

    async def get_user_connection_entries(
        self, user_id: str
    ) -> list[tuple[str, WebSocket]]:
        async with self._lock:
            conn_ids = list(self._user_connections.get(user_id, set()))
            return [
                (cid, self._connections[cid])
                for cid in conn_ids
                if cid in self._connections
            ]

    async def clear_user_bindings(self, user_id: str) -> None:
        async with self._lock:
            self._user_channel_bindings.pop(user_id, None)

    async def get_by_channel(self, channel: str) -> list[WebSocket]:
        async with self._lock:
            conn_ids = self._channel_connections.get(channel, set())
            return [self._connections[cid] for cid in conn_ids if cid in self._connections]

    async def link_user(self, user_id: str, connection_id: str) -> None:
        async with self._lock:
            self._user_connections[user_id].add(connection_id)

    async def subscribe(self, connection_id: str, channel: str) -> None:
        count = 0
        async with self._lock:
            self._channel_connections[channel].add(connection_id)
            self._connection_channels[connection_id].add(channel)
            count = len(self._channel_connections[channel])
        for listener in self._subscription_listeners:
            try:
                res = listener(channel, count)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

    async def unsubscribe(self, connection_id: str, channel: str) -> None:
        count = 0
        async with self._lock:
            self._channel_connections[channel].discard(connection_id)
            count = len(self._channel_connections[channel])
            if not self._channel_connections[channel]:
                del self._channel_connections[channel]
            self._connection_channels[connection_id].discard(channel)
        for listener in self._subscription_listeners:
            try:
                res = listener(channel, count)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

    async def get_subscriptions(self, connection_id: str) -> set[str]:
        async with self._lock:
            return set(self._connection_channels.get(connection_id, set()))

    async def broadcast(self, channel: str, data: bytes) -> int:
        async with self._lock:
            conn_ids = list(self._channel_connections.get(channel, set()))
            targets = [
                (cid, self._connections[cid])
                for cid in conn_ids
                if cid in self._connections
            ]

        sent = 0
        failed: list[str] = []
        for cid, ws in targets:
            try:
                await ws.send_bytes(data)
                sent += 1
            except Exception:
                failed.append(cid)

        for cid in failed:
            await self.deregister(cid)

        return sent

    async def bind_user_channel(self, user_id: str, channel: str) -> None:
        """Record a persistent user↔channel intent binding (survives disconnect)."""
        async with self._lock:
            self._user_channel_bindings[user_id].add(channel)

    async def unbind_user_channel(self, user_id: str, channel: str) -> None:
        """Remove a persistent user↔channel intent binding."""
        async with self._lock:
            self._user_channel_bindings[user_id].discard(channel)
            if not self._user_channel_bindings[user_id]:
                self._user_channel_bindings.pop(user_id, None)

    @property
    def active_connections(self) -> int:
        return len(self._connections)
