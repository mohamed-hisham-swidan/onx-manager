import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.monitoring.infrastructure.rcon_client import (
    AsyncRCONClient,
    AuthenticationError,
    PersistentRCONClient,
    RCONError,
)


def _rcon_packet(req_id: int, ptype: int, body: str = "") -> bytes:
    payload = body.encode("utf-8") + b"\x00"
    return struct.pack("<iii", 10 + len(payload), req_id, ptype) + payload + b"\x00\x00"


class _MockRCONServer:
    """Minimal asyncio RCON server for exercising the real wire protocol."""

    def __init__(
        self,
        password: str = "pw",
        resp_id: int | None = None,
        fragment: bool = False,
    ) -> None:
        self._password = password
        self._resp_id = resp_id
        self._fragment = fragment
        self._server: asyncio.AbstractServer | None = None
        self.port: int = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def _write_response(
        self, writer: asyncio.StreamWriter, req_id: int, ptype: int, body: str
    ) -> None:
        """Write one packet, or emulate vanilla fragmentation when payload exceeds 4096 chars."""
        if not self._fragment or len(body) <= 4096:
            writer.write(_rcon_packet(req_id, ptype, body))
            return
        # Vanilla RconClient.sendCmdResponse splits >4096-char output into
        # multiple packets sharing the same request-id and type 0.
        while body:
            writer.write(_rcon_packet(req_id, ptype, body[:4096]))
            body = body[4096:]

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                header = await reader.readexactly(12)
                length, req_id, ptype = struct.unpack("<iii", header)
                body = await reader.readexactly(length - 8)
                if ptype == 3:
                    password = body[:-2].rstrip(b"\x00").decode()
                    auth_id = req_id if password == self._password else -1
                    writer.write(_rcon_packet(auth_id, 2))
                else:
                    resp_id = self._resp_id if self._resp_id is not None else req_id
                    self._write_response(writer, resp_id, 0, f"out:{body[:-2].decode()}")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            writer.close()
            with patch("app.modules.monitoring.infrastructure.rcon_client.logger"):
                await writer.wait_closed()


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


@pytest.mark.asyncio
async def test_send_command_rejects_mismatched_response_id() -> None:
    """A desynced connection (wrong request-id) must raise instead of returning stale data."""
    server = _MockRCONServer(resp_id=999)
    await server.start()
    client = AsyncRCONClient("127.0.0.1", server.port, "pw", timeout=2)
    try:
        await client.connect()
        with pytest.raises(RCONError):
            await client.send_command("tps")
    finally:
        await client.close()
        await server.close()


@pytest.mark.asyncio
async def test_persistent_send_command_cancelled_closes_connection() -> None:
    """Cancellation (e.g. collect_all timeout) must drop the desynced connection."""
    client = PersistentRCONClient("127.0.0.1", 25575, "pw", timeout=0.2)
    inner = AsyncMock()
    inner._writer = object()
    inner.send_command = AsyncMock(side_effect=asyncio.CancelledError)

    async def ensure() -> object:
        client._client = inner
        return inner

    client.ensure_connected = ensure  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await client.send_command("tps")

    assert client._client is None
    inner.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_persistent_commands_against_real_server() -> None:
    """End-to-end: auth + command against the wire protocol, response verified."""
    server = _MockRCONServer(password="s3cret")
    await server.start()
    client = PersistentRCONClient("127.0.0.1", server.port, "s3cret", timeout=2, max_retries=1)
    try:
        await client.ensure_connected()
        assert client.is_connected
        result = await client.send_command("list")
        assert result.rstrip("\x00") == "out:list"
    finally:
        await client.close()
        await server.close()


@pytest.mark.asyncio
async def test_single_packet_response_survives_fragment_enabled_server() -> None:
    """With fragmentation enabled, short single-packet responses still work unchanged.

    Vanilla RconClient.sendCmdResponse only splits responses longer than 4096
    characters; /tps and a small /list stay below that, so the client must keep
    reading a single packet without regression.
    """
    server = _MockRCONServer(fragment=True)
    await server.start()
    client = PersistentRCONClient("127.0.0.1", server.port, "pw", timeout=2, max_retries=1)
    try:
        await client.ensure_connected()
        result = await client.send_command("list")
        assert result.rstrip("\x00") == "out:list"
        assert len(result) < 4096
    finally:
        await client.close()
        await server.close()
