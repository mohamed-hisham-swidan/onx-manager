from __future__ import annotations

import time
from collections import defaultdict


class WSRateLimiter:
    def __init__(self, max_messages: int = 50, window_seconds: int = 1) -> None:
        self._max_messages = max_messages
        self._window_seconds = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup: float = 0.0

    def check(self, connection_id: str) -> bool:
        now = time.time()
        self._cleanup_if_needed(now)
        window_start = now - self._window_seconds
        self._buckets[connection_id] = [t for t in self._buckets[connection_id] if t > window_start]
        if len(self._buckets[connection_id]) >= self._max_messages:
            return False
        self._buckets[connection_id].append(now)
        return True

    def _cleanup_if_needed(self, now: float) -> None:
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now
        cutoff = now - self._window_seconds * 2
        self._buckets = defaultdict(
            list,
            {k: [t for t in v if t > cutoff] for k, v in self._buckets.items() if any(t > cutoff for t in v)},
        )

    @property
    def max_messages(self) -> int:
        return self._max_messages

    @property
    def window_seconds(self) -> int:
        return self._window_seconds
