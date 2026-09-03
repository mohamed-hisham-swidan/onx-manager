from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app.core.command_bus import CommandResult
from app.core.idempotency import (
    IdempotencyKey,
    IdempotencyMiddleware,
    InMemoryIdempotencyStore,
)


@dataclass
class DummyCommand:
    idempotency_key: IdempotencyKey
    name: str


@pytest.mark.asyncio
async def test_concurrent_identical_keys_execute_once() -> None:
    """ISS-002: Launch two identical requests simultaneously; call_next is called exactly once."""
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(store)

    key = IdempotencyKey("idem-concurrent-1")
    cmd1 = DummyCommand(idempotency_key=key, name="cmd1")
    cmd2 = DummyCommand(idempotency_key=key, name="cmd2")

    call_count = 0

    async def slow_call_next(cmd: DummyCommand) -> CommandResult:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.1)  # 100ms delay
        return CommandResult(success=True, data={"executed_for": cmd.name, "count": call_count})

    res1, res2 = await asyncio.gather(
        middleware(cmd1, slow_call_next),
        middleware(cmd2, slow_call_next),
    )

    assert call_count == 1, (
        f"call_next should only have been called once, but was called {call_count} times"
    )
    assert res1.success is True
    assert res2.success is True
    assert res1.data == res2.data
    assert res1.data["count"] == 1


@pytest.mark.asyncio
async def test_exception_in_call_next_clears_reservation() -> None:
    """ISS-002: If call_next raises an exception, reservation is cleared and retry succeeds."""
    store = InMemoryIdempotencyStore()
    middleware = IdempotencyMiddleware(store)

    key = IdempotencyKey("idem-fail-retry")
    cmd = DummyCommand(idempotency_key=key, name="cmd")

    should_fail = True

    async def flaky_call_next(_cmd: DummyCommand) -> CommandResult:
        nonlocal should_fail
        if should_fail:
            raise RuntimeError("Temporary error")
        return CommandResult(success=True, data={"status": "recovered"})

    with pytest.raises(RuntimeError, match="Temporary error"):
        await middleware(cmd, flaky_call_next)

    # Next attempt should succeed, not be stuck or blocked
    should_fail = False
    result = await middleware(cmd, flaky_call_next)
    assert result.success is True
    assert result.data["status"] == "recovered"
