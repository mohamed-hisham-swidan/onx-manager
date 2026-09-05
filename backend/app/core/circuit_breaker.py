from __future__ import annotations

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
        max_failures: int | None = None,
        timeout_seconds: float | None = None,
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
    def max_failures(self) -> int:
        if self._max_failures is not None:
            return self._max_failures
        try:
            from app.core.settings_store import get_live_settings

            return get_live_settings().circuit_breaker_max_failures
        except RuntimeError:
            return 5

    @property
    def timeout_seconds(self) -> float:
        if self._timeout is not None:
            return self._timeout
        try:
            from app.core.settings_store import get_live_settings

            return float(get_live_settings().circuit_breaker_timeout_seconds)
        except RuntimeError:
            return 30.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.timeout_seconds:
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
            if hasattr(coro, "close"):
                coro.close()
            raise CircuitBreakerOpenError(f"Circuit '{self._name}' is open")

        try:
            result = await coro
            self._on_success()
            return result
        except Exception:
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
        except Exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.CLOSED)
        self._failure_count = 0

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.max_failures:
            self._transition_to(CircuitState.OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        if self._state == new_state:
            return
        logger.info(
            "Circuit breaker state change: name=%s old=%s new=%s failure_count=%d",
            self._name,
            self._state.value,
            new_state.value,
            self._failure_count,
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
