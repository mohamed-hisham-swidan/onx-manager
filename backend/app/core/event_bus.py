from __future__ import annotations

import asyncio
import itertools
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DomainEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event_type: str = ""
    timestamp: float = Field(default_factory=time.time)
    correlation_id: str = ""
    schema_version: int = 1


class EventHandler(ABC):
    @abstractmethod
    async def handle(self, event: DomainEvent) -> None: ...


class Priority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class Subscription:
    handler: EventHandler
    priority: int = Priority.NORMAL
    cancelled: bool = False
    # Optional per-subscription timeout override (seconds).
    # When None the global EventBus._subscriber_timeout is used.
    timeout: float | None = None


@dataclass
class DeadLetterEntry:
    event: DomainEvent
    error: str
    timestamp: float = field(default_factory=time.time)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscription]] = {}
        self._dead_letter_queue: deque[DeadLetterEntry] = deque(maxlen=1000)
        self._retry_attempts: int | None = None
        self._subscriber_timeout: float = 10.0

    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        priority: int = Priority.NORMAL,
        timeout: float | None = None,
    ) -> Subscription:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        sub = Subscription(handler=handler, priority=priority, timeout=timeout)
        self._subscribers[event_type].append(sub)
        self._subscribers[event_type].sort(key=lambda s: s.priority)
        return sub

    def unsubscribe(self, subscription: Subscription) -> None:
        subscription.cancelled = True

    @property
    def dead_letter_count(self) -> int:
        return len(self._dead_letter_queue)

    @property
    def dead_letter_queue(self) -> list[DeadLetterEntry]:
        return list(self._dead_letter_queue)

    @property
    def retry_attempts(self) -> int:
        if self._retry_attempts is not None:
            return self._retry_attempts
        try:
            from app.core.settings_store import get_live_settings

            return get_live_settings().event_bus_retry_attempts
        except RuntimeError:
            return 3

    @retry_attempts.setter
    def retry_attempts(self, value: int | None) -> None:
        self._retry_attempts = value

    async def publish(self, event: DomainEvent) -> None:
        if not event.event_type:
            event.event_type = type(event).__name__

        subscribers = self._subscribers.get(event.event_type, [])
        if not subscribers:
            return

        active = [s for s in subscribers if not s.cancelled]
        if not active:
            return

        active.sort(key=lambda s: s.priority)
        for _prio, group in itertools.groupby(active, key=lambda s: s.priority):
            tasks = [self._dispatch_with_retry(event, sub) for sub in group]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _dispatch_with_retry(
        self,
        event: DomainEvent,
        subscription: Subscription,
    ) -> None:
        last_error: Exception | None = None
        max_attempts = self.retry_attempts
        # Use per-subscription timeout override when set; otherwise use the global.
        effective_timeout = (
            subscription.timeout if subscription.timeout is not None else self._subscriber_timeout
        )
        for attempt in range(max_attempts):
            try:
                async with asyncio.timeout(effective_timeout):
                    await subscription.handler.handle(event)
                return
            except TimeoutError:
                last_error = TimeoutError("Subscriber timed out")
                logger.warning(
                    "Subscriber timeout: event_type=%s attempt=%d",
                    event.event_type,
                    attempt + 1,
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "Subscriber error: event_type=%s attempt=%d error=%s",
                    event.event_type,
                    attempt + 1,
                    str(e),
                )

            if attempt < max_attempts - 1:
                await asyncio.sleep(2**attempt)

        self._dead_letter_queue.append(
            DeadLetterEntry(
                event=event,
                error=f"{type(last_error).__name__}: {last_error}",
            ),
        )
        logger.error(
            "Event moved to dead letter queue: event_type=%s error=%s",
            event.event_type,
            str(last_error),
        )
