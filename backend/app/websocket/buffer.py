from __future__ import annotations

import time
from collections import defaultdict


class BufferedMessage:
    __slots__ = ("data", "timestamp", "channels")

    def __init__(self, data: dict, timestamp: float, channels: list[str]) -> None:
        self.data = data
        self.timestamp = timestamp
        self.channels = channels


class OfflineMessageBuffer:
    def __init__(self, max_events: int = 100, ttl_seconds: int = 300) -> None:
        self._max_events = max_events
        self._ttl_seconds = ttl_seconds
        self._buffer: dict[str, list[BufferedMessage]] = defaultdict(list)
        self._last_cleanup: float = 0.0

    def add(self, user_id: str, message: BufferedMessage) -> None:
        self._cleanup_if_needed()
        user_buffer = self._buffer[user_id]
        user_buffer.append(message)
        if len(user_buffer) > self._max_events:
            self._buffer[user_id] = user_buffer[-self._max_events :]

    def get_pending(self, user_id: str) -> list[BufferedMessage]:
        self._cleanup_if_needed()
        return list(self._buffer.get(user_id, []))

    def clear(self, user_id: str) -> None:
        self._buffer.pop(user_id, None)

    def _cleanup_if_needed(self) -> None:
        now = time.time()
        if now - self._last_cleanup < 30:
            return
        self._last_cleanup = now
        cutoff = now - self._ttl_seconds
        for user_id, messages in list(self._buffer.items()):
            fresh = [m for m in messages if m.timestamp > cutoff]
            if fresh:
                self._buffer[user_id] = fresh
            else:
                del self._buffer[user_id]

    @property
    def max_events(self) -> int:
        return self._max_events

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def total_buffered(self, user_id: str | None = None) -> int:
        if user_id:
            return len(self._buffer.get(user_id, []))
        return sum(len(v) for v in self._buffer.values())
