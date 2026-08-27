from __future__ import annotations

from abc import ABC
from typing import Any

from app.core.event_bus import DomainEvent


class AggregateRoot(ABC):
    _domain_events: list[DomainEvent]

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self._domain_events = []

    def collect_events(self) -> list[DomainEvent]:
        events = list(self._domain_events)
        self._domain_events.clear()
        return events

    def _add_event(self, event: DomainEvent) -> None:
        self._domain_events.append(event)
