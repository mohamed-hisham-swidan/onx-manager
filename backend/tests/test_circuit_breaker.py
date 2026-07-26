import asyncio

import pytest

from app.core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState


@pytest.mark.asyncio
class TestCircuitBreaker:
    async def test_initial_state_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    async def test_successful_call_resets_failures(self) -> None:
        cb = CircuitBreaker("test", max_failures=3)

        async def fail() -> None:
            raise ValueError("oops")

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail())

        assert cb.failure_count == 2

        async def succeed() -> str:
            return "ok"

        result = await cb.call(succeed())
        assert result == "ok"
        assert cb.failure_count == 0

    async def test_opens_after_max_failures(self) -> None:
        cb = CircuitBreaker("test", max_failures=3, timeout_seconds=60)

        async def fail() -> None:
            raise ValueError("oops")

        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(fail())

        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3

    async def test_open_state_rejects_calls(self) -> None:
        cb = CircuitBreaker("test", max_failures=1, timeout_seconds=60)

        async def fail() -> None:
            raise ValueError("nope")

        with pytest.raises(ValueError):
            await cb.call(fail())

        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(fail())

    async def test_transitions_to_half_open_after_timeout(self) -> None:
        cb = CircuitBreaker("test", max_failures=1, timeout_seconds=0.1)

        async def fail() -> None:
            raise ValueError("nope")

        with pytest.raises(ValueError):
            await cb.call(fail())

        assert cb.state == CircuitState.OPEN
        await asyncio.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    async def test_half_open_success_closes(self) -> None:
        cb = CircuitBreaker("test", max_failures=1, timeout_seconds=0.1)

        async def fail() -> None:
            raise ValueError("nope")

        with pytest.raises(ValueError):
            await cb.call(fail())

        await asyncio.sleep(0.15)

        async def succeed() -> str:
            return "recovered"

        result = await cb.call(succeed())
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED

    async def test_events_are_recorded(self) -> None:
        cb = CircuitBreaker("test", max_failures=2, timeout_seconds=60)

        async def fail() -> None:
            raise ValueError("nope")

        with pytest.raises(ValueError):
            await cb.call(fail())

        assert len(cb.events) == 0

        with pytest.raises(ValueError):
            await cb.call(fail())

        assert len(cb.events) == 1
        assert cb.events[0].state == CircuitState.OPEN
