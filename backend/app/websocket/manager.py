from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict

from fastapi import WebSocket


class ConnectionRegistry:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._user_connections: dict[str, set[str]] = defaultdict(set)
        self._channel_connections: dict[str, set[str]] = defaultdict(set)
        self._connection_channels: dict[str, set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def register(self, connection_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._connections[connection_id] = ws

    async def deregister(self, connection_id: str) -> None:
        async with self._lock:
            self._connections.pop(connection_id, None)
            channels = self._connection_channels.pop(connection_id, set())
            for ch in channels:
                self._channel_connections[ch].discard(connection_id)
                if not self._channel_connections[ch]:
                    del self._channel_connections[ch]
            for user_id, conns in list(self._user_connections.items()):
                conns.discard(connection_id)
                if not conns:
                    del self._user_connections[user_id]

    async def get(self, connection_id: str) -> WebSocket | None:
        async with self._lock:
            return self._connections.get(connection_id)

    async def get_by_user(self, user_id: str) -> list[WebSocket]:
        async with self._lock:
            conn_ids = self._user_connections.get(user_id, set())
            return [self._connections[cid] for cid in conn_ids if cid in self._connections]

    async def get_by_channel(self, channel: str) -> list[WebSocket]:
        async with self._lock:
            conn_ids = self._channel_connections.get(channel, set())
            return [self._connections[cid] for cid in conn_ids if cid in self._connections]

    async def link_user(self, user_id: str, connection_id: str) -> None:
        async with self._lock:
            self._user_connections[user_id].add(connection_id)

    async def subscribe(self, connection_id: str, channel: str) -> None:
        async with self._lock:
            self._channel_connections[channel].add(connection_id)
            self._connection_channels[connection_id].add(channel)

    async def unsubscribe(self, connection_id: str, channel: str) -> None:
        async with self._lock:
            self._channel_connections[channel].discard(connection_id)
            if not self._channel_connections[channel]:
                del self._channel_connections[channel]
            self._connection_channels[connection_id].discard(channel)

    async def get_subscriptions(self, connection_id: str) -> set[str]:
        async with self._lock:
            return set(self._connection_channels.get(connection_id, set()))

    async def broadcast(self, channel: str, data: bytes) -> int:
        sent = 0
        async with self._lock:
            conn_ids = list(self._channel_connections.get(channel, set()))
            for cid in conn_ids:
                ws = self._connections.get(cid)
                if ws is not None:
                    try:
                        await ws.send_bytes(data)
                        sent += 1
                    except Exception:
                        pass
        return sent

    @property
    def active_connections(self) -> int:
        return len(self._connections)
