import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.monitoring.infrastructure.rcon_client import (
    AuthenticationError,
    PersistentRCONClient,
    RCONError,
)


@pytest.mark.asyncio
async def test_send_command_reuses_existing_connection() -> None:
    client = PersistentRCONClient("127.0.0.1", 25575, "pw")
    inner = MagicMock()
    inner._writer = object()
    inner.send_command = AsyncMock(return_value="ok")
    client._client = inner

    result = await client.send_command("list")

    assert result == "ok"
    inner.send_command.assert_awaited_once_with("list")
    assert client.is_connected


@pytest.mark.asyncio
async def test_send_command_connects_when_disconnected() -> None:
    client = PersistentRCONClient("127.0.0.1", 25575, "pw")
    inner = MagicMock()
    inner._writer = object()
    inner.send_command = AsyncMock(return_value="ok")
    client.ensure_connected = AsyncMock(return_value=inner)  # type: ignore[method-assign]

    result = await client.send_command("tps")

    assert result == "ok"
    client.ensure_connected.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_command_reconnects_after_failure() -> None:
    client = PersistentRCONClient("127.0.0.1", 25575, "pw", max_retries=3, retry_delay=0.01)
    inner = MagicMock()
    inner._writer = object()
    inner.close = AsyncMock()
    inner.send_command = AsyncMock(side_effect=[RCONError("boom"), "recovered"])

    async def ensure() -> object:
        client._client = inner
        return inner

    client.ensure_connected = ensure  # type: ignore[method-assign]

    result = await client.send_command("list")

    assert result == "recovered"
    assert inner.send_command.await_count == 2
    inner.close.assert_awaited()


@pytest.mark.asyncio
async def test_send_command_raises_after_all_retries() -> None:
    client = PersistentRCONClient("127.0.0.1", 25575, "pw", max_retries=2, retry_delay=0.01)
    inner = MagicMock()
    inner._writer = object()
    inner.send_command = AsyncMock(side_effect=RCONError("nope"))
    client.ensure_connected = AsyncMock(return_value=inner)  # type: ignore[method-assign]
    client.close = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(RCONError):
        await client.send_command("list")

    assert inner.send_command.await_count == 2


@pytest.mark.asyncio
async def test_send_command_failure_does_not_deadlock_lock() -> None:
    client = PersistentRCONClient("127.0.0.1", 25575, "pw", max_retries=1, retry_delay=0)
    inner = MagicMock()
    inner._writer = object()
    inner.close = AsyncMock()
    inner.send_command = AsyncMock(side_effect=RCONError("boom"))

    async def failing_ensure() -> object:
        client._client = inner
        return inner

    client.ensure_connected = failing_ensure  # type: ignore[method-assign]

    with pytest.raises(RCONError):
        await client.send_command("tps")

    inner.close.assert_awaited_once()
    assert client._client is None

    # The lock must be free: a subsequent successful command must complete
    # within a strict timeout instead of hanging on the deadlock.
    ok_inner = MagicMock()
    ok_inner._writer = object()
    ok_inner.send_command = AsyncMock(return_value="ok")

    async def ok_ensure() -> object:
        return ok_inner

    client.ensure_connected = ok_ensure  # type: ignore[method-assign]
    result = await asyncio.wait_for(client.send_command("list"), timeout=2.0)
    assert result == "ok"


@pytest.mark.asyncio
async def test_ensure_connected_auth_failure_clears_client() -> None:
    client = PersistentRCONClient("127.0.0.1", 25575, "bad")
    failing = MagicMock()
    failing.connect = AsyncMock(side_effect=AuthenticationError("auth failed"))
    with (
        patch(
            "app.modules.monitoring.infrastructure.rcon_client.AsyncRCONClient",
            return_value=failing,
        ),
        pytest.raises(AuthenticationError),
    ):
        await client.ensure_connected()

    assert client._client is None


@pytest.mark.asyncio
async def test_close_clears_client() -> None:
    client = PersistentRCONClient("127.0.0.1", 25575, "pw")
    inner = MagicMock()
    inner.close = AsyncMock()
    client._client = inner

    await client.close()

    inner.close.assert_awaited_once()
    assert client._client is None


@pytest.mark.asyncio
async def test_commands_serialized_under_lock() -> None:
    client = PersistentRCONClient("127.0.0.1", 25575, "pw")
    inner = MagicMock()
    inner._writer = object()

    async def slow_send(cmd: str) -> str:
        await asyncio.sleep(0.02)
        return f"resp:{cmd}"

    inner.send_command = slow_send
    client._client = inner

    results = await asyncio.gather(
        client.send_command("tps"),
        client.send_command("list"),
    )

    assert results == ["resp:tps", "resp:list"]
