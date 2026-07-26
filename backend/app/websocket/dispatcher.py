from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from app.core.event_bus import DomainEvent, EventBus, EventHandler
from app.websocket.buffer import BufferedMessage, OfflineMessageBuffer
from app.websocket.manager import ConnectionRegistry
from app.websocket.serializers import MessageSerializer

logger = logging.getLogger(__name__)


class EventDispatcher(EventHandler):
    def __init__(
        self,
        registry: ConnectionRegistry,
        buffer: OfflineMessageBuffer,
        event_bus: EventBus,
    ) -> None:
        self._registry = registry
        self._buffer = buffer
        self._event_bus = event_bus
        self._subscriptions: list[Any] = []

    async def start(self, event_types: list[str] | None = None) -> None:
        if event_types:
            for et in event_types:
                sub = self._event_bus.subscribe(et, self)
                self._subscriptions.append(sub)
                logger.info("EventDispatcher subscribed to %s", et)

    async def stop(self) -> None:
        for sub in self._subscriptions:
            self._event_bus.unsubscribe(sub)
        self._subscriptions.clear()

    async def handle(self, event: DomainEvent) -> None:
        channels = self._resolve_channels(event)
        message = MessageSerializer.event_to_message(event)
        serialized = message.to_json()

        sent = set()
        for channel in channels:
            conn_ids = await self._get_connection_ids_for_channel(channel)
            for cid in conn_ids:
                if cid in sent:
                    continue
                sent.add(cid)
                ws = await self._registry.get(cid)
                if ws is not None:
                    try:
                        await ws.send_bytes(serialized)
                    except Exception:
                        pass

        user_ids_from_disconnected = await self._find_disconnected_user_ids(channels, sent)
        for user_id in user_ids_from_disconnected:
            self._buffer.add(
                user_id,
                BufferedMessage(
                    data=message.to_dict(),
                    timestamp=event.timestamp,
                    channels=list(channels),
                ),
            )

    async def _get_connection_ids_for_channel(self, channel: str) -> list[str]:
        async with self._registry._lock:
            conn_ids = list(self._registry._channel_connections.get(channel, set()))
        return conn_ids

    async def _find_disconnected_user_ids(self, channels: set[str], sent_connections: set[str]) -> set[str]:
        user_ids: set[str] = set()
        async with self._registry._lock:
            for user_id, conns in self._registry._user_connections.items():
                has_any_channel = False
                for ch in channels:
                    if ch in self._registry._channel_connections:
                        if any(c in conns for c in self._registry._channel_connections[ch]):
                            has_any_channel = True
                            break
                if has_any_channel and not conns.intersection(sent_connections):
                    user_ids.add(user_id)
        return user_ids

    def _resolve_channels(self, event: DomainEvent) -> set[str]:
        channels: set[str] = set()
        event_type = event.event_type

        server_id = ""
        if hasattr(event, "server_id"):
            server_id = event.server_id

        if server_id:
            channels.add(f"server:{server_id}")
            channels.add("server:*")

        if "Backup" in event_type:
            channels.add("backup:*")
        if "Plugin" in event_type:
            channels.add("plugin:*")
        if "Alert" in event_type or "Metric" in event_type:
            channels.add("monitoring:*")
            if server_id:
                channels.add(f"monitoring:{server_id}")

        if not channels:
            channels.add("server:*")

        return channels


class MetricsBatcher:
    def __init__(self, registry: ConnectionRegistry, window_seconds: float = 2.0) -> None:
        self._registry = registry
        self._window_seconds = window_seconds
        self._samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._batch_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def add_sample(self, server_id: str, sample: dict[str, Any]) -> None:
        self._samples[server_id].append(sample)

    async def _batch_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._window_seconds)
            await self._flush()

    async def _flush(self) -> None:
        for server_id, samples in self._samples.items():
            if not samples:
                continue
            message = MessageSerializer.metrics_batch_message(server_id, samples)
            serialized = message.to_json()
            await self._registry.broadcast(f"metrics:{server_id}", serialized)
        self._samples.clear()
