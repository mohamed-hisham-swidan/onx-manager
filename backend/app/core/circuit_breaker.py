from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitEvent:
    state: CircuitState
    timestamp: float
    failure_count: int


class CircuitBreaker:
    def __init__(
        self,
        name: str = "default",
        max_failures: int = 5,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._name = name
        self._max_failures = max_failures
        self._timeout = timeout_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_start = 0.0
        self._events: list[CircuitEvent] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self._timeout:
                self._transition_to(CircuitState.HALF_OPEN)
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def events(self) -> list[CircuitEvent]:
        return list(self._events)

    async def call(self, coro: Coroutine[Any, Any, Any]) -> Any:
        current = self.state

        if current == CircuitState.OPEN:
            raise CircuitBreakerOpenError(f"Circuit '{self._name}' is open")

        try:
            result = await coro
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    async def call_factory(self, factory: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
        current = self.state

        if current == CircuitState.OPEN:
            raise CircuitBreakerOpenError(f"Circuit '{self._name}' is open")

        coro = factory()
        try:
            result = await coro
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.CLOSED)
        self._failure_count = 0

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self._max_failures:
            self._transition_to(CircuitState.OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        if self._state == new_state:
            return
        logger.info(
            "Circuit breaker state change",
            name=self._name,
            old=self._state.value,
            new=new_state.value,
            failure_count=self._failure_count,
        )
        self._state = new_state
        self._events.append(
            CircuitEvent(
                state=new_state,
                timestamp=time.time(),
                failure_count=self._failure_count,
            ),
        )
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_start = time.time()


class CircuitBreakerOpenError(Exception):
    pass
