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

# ---------------------------------------------------------------------------
# Decision 1 — Explicit WS delivery allowlist (31 event types).
# Only these events are subscribed by EventDispatcher at startup.
# Auth, metrics, and instance-level exposure events are intentionally excluded
# to prevent cross-user privacy leaks and duplicate metric broadcasts.
# ---------------------------------------------------------------------------
WS_DISPATCH_ALLOWLIST: list[str] = [
    # Server lifecycle
    "ServerCreatedEvent",
    "ServerStartingEvent",
    "ServerStartedEvent",
    "ServerStoppingEvent",
    "ServerStoppedEvent",
    "ServerCrashedEvent",
    "ServerConfigChangedEvent",
    "ServerDeletedEvent",
    "ServerDiscoveredEvent",
    "ServerVanishedEvent",
    # Backup
    "BackupStartedEvent",
    "BackupCompletedEvent",
    "BackupFailedEvent",
    "BackupRestoredEvent",
    "BackupDeletedEvent",
    # Plugin
    "PluginInstalledEvent",
    "PluginEnabledEvent",
    "PluginDisabledEvent",
    "PluginUninstalledEvent",
    "PluginUpdatedEvent",
    # Exposure (server-scoped only)
    "ServerExposureEnabledEvent",
    "ServerExposureDisabledEvent",
    "ServerExposureRemovedEvent",
    # Monitoring
    "AlertTriggeredEvent",
    "AlertResolvedEvent",
    # Health / crash pipeline products
    "EvidenceCollectedEvent",
    "CrashClassifiedEvent",
    "RecoveryTriggeredEvent",
    "RecoveryFailedEvent",
    "RecoverySucceededEvent",
    "HealthStatusChangedEvent",
]


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
        """Return user IDs that have a channel binding overlapping *channels*
        but hold no live connection (and were therefore not reached by the
        send loop).  After the scan, prune stale bindings for offline users
        whose buffer bucket is empty (no pending data) to prevent unbounded
        growth.
        """
        user_ids: set[str] = set()
        offline_with_no_match: list[str] = []
        async with self._registry._lock:
            for user_id, bound_channels in list(self._registry._user_channel_bindings.items()):
                # Skip users that have at least one live connection — they
                # were already reached (or skipped for lack of subscription).
                live_conns = self._registry._user_connections.get(user_id, set())
                if live_conns:
                    continue
                # Offline user: check whether any bound channel overlaps the
                # event's routed channels.
                if not bound_channels.isdisjoint(channels):
                    # Matching binding → buffer the event for this user.
                    user_ids.add(user_id)
                else:
                    # Offline and no channel match — candidate for eviction if
                    # their buffer is also empty.
                    offline_with_no_match.append(user_id)
        # Eviction pass (outside registry lock): remove bindings for offline
        # users who have no buffered data (drained or TTL-expired).
        evict: list[str] = [
            uid for uid in offline_with_no_match
            if self._buffer.total_buffered(uid) == 0
        ]
        if evict:
            async with self._registry._lock:
                for uid in evict:
                    self._registry._user_channel_bindings.pop(uid, None)
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
    def __init__(self, registry: ConnectionRegistry, window_seconds: float = 0.2) -> None:
        self._registry = registry
        self._window_seconds = window_seconds
        self._samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def set_window_seconds(self, window_seconds: float) -> None:
        self._window_seconds = max(0.1, min(60.0, float(window_seconds)))

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
