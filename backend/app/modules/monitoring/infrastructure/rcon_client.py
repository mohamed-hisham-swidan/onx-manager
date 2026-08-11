from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import struct

logger = logging.getLogger(__name__)

PACKET_LOGIN = 3
PACKET_COMMAND = 2
PACKET_AUTH_RESPONSE = 2
PACKET_RESPONSE = 0


class RCONError(Exception):
    pass


class AuthenticationError(RCONError):
    pass


class AsyncRCONClient:
    def __init__(self, host: str, port: int, password: str, timeout: float = 5.0) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._request_id = 1

    async def connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._timeout,
            )
        except (OSError, TimeoutError) as exc:
            raise RCONError(f"Failed to connect to {self._host}:{self._port}: {exc}") from exc

        await self._authenticate()

    async def _authenticate(self) -> None:
        self._request_id += 1
        req_id = self._request_id
        await self._send_packet(req_id, PACKET_LOGIN, self._password)
        resp_id, ptype, _ = await self._read_packet()
        if ptype == PACKET_AUTH_RESPONSE and resp_id == req_id and resp_id != -1:
            return
        raise AuthenticationError("RCON authentication failed")

    async def send_command(self, command: str) -> str:
        self._request_id += 1
        req_id = self._request_id
        await self._send_packet(req_id, PACKET_COMMAND, command)
        resp_id, ptype, body = await self._read_packet()
        if resp_id != req_id or ptype != PACKET_RESPONSE:
            raise RCONError(
                f"RCON response mismatch (expected request-id {req_id}, got {resp_id} type {ptype})"
            )
        return body

    async def _send_packet(self, req_id: int, ptype: int, body: str) -> None:
        if self._writer is None:
            raise RCONError("Not connected")
        body_bytes = body.encode("utf-8") + b"\x00"
        length = 10 + len(body_bytes)
        data = struct.pack("<iii", length, req_id, ptype) + body_bytes + b"\x00\x00"
        self._writer.write(data)
        await self._writer.drain()

    async def _read_packet(self) -> tuple[int, int, str]:
        if self._reader is None:
            raise RCONError("Not connected")
        raw = await asyncio.wait_for(self._reader.readexactly(12), timeout=self._timeout)
        length, req_id, ptype = struct.unpack("<iii", raw)
        body_bytes = await asyncio.wait_for(
            self._reader.readexactly(length - 8), timeout=self._timeout
        )
        body = body_bytes[:-2].decode("utf-8", errors="replace")
        return req_id, ptype, body

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
            self._writer = None
            self._reader = None


class PersistentRCONClient:
    """Long-lived RCON connection reused across collection ticks.

    The Minecraft server opens a fresh RCON session for every TCP connection
    (logging "Thread RCON Client started / shutting down" each time). Keeping
    one connection open avoids that reconnect churn and the small cost of
    authenticating every poll. The connection is transparently re-established
    if the server restarts or drops it.
    """

    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        timeout: float = 5.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._lock = asyncio.Lock()
        self._client: AsyncRCONClient | None = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def password(self) -> str:
        return self._password

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client._writer is not None

    async def ensure_connected(self) -> AsyncRCONClient:
        if self._client is not None and self._client._writer is not None:
            return self._client
        self._client = AsyncRCONClient(self._host, self._port, self._password, self._timeout)
        try:
            await self._client.connect()
        except Exception:
            self._client = None
            raise
        return self._client

    async def send_command(self, command: str) -> str:
        async with self._lock:
            last_error: Exception | None = None
            for attempt in range(self._max_retries):
                try:
                    client = await self.ensure_connected()
                    return await client.send_command(command)
                except asyncio.CancelledError:
                    # A timeout (e.g. wait_for from the collector) cancelled us
                    # mid-command; the response for the interrupted command may
                    # still be in flight, so the connection is desynced and must
                    # not be reused. Close it before propagating the cancel.
                    await self._close_unlocked()
                    raise
                except Exception as exc:
                    last_error = exc
                    await self._close_unlocked()
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(self._retry_delay)
            raise last_error if last_error is not None else RCONError("RCON send failed")

    async def _close_unlocked(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def close(self) -> None:
        async with self._lock:
            await self._close_unlocked()


def _strip_mc_color_codes(text: str) -> str:
    """Remove Minecraft color/format codes (``§`` + one hex/letter char)."""
    return re.sub(r"\u00a7[0-9a-fk-or]", "", text)


def _first_number(text: str) -> float | None:
    match = re.search(r"\d+\.?\d*", text)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def parse_tps(response: str) -> float | None:
    text = _strip_mc_color_codes(response)
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("TPS from last"):
            # e.g. "TPS from last 5s, 1m, 5m, 15m: 20.0, 20.0, 20.0, 20.0"
            # first value after the colon is the "last 5s" TPS.
            after = line.split(":", 1)[1] if ":" in line else line
            value = _first_number(after)
            if value is not None:
                return value
            continue
        if "Overall TPS" in line:
            for sep in ("=", ":"):
                if sep in line:
                    value = _first_number(line.split(sep, 1)[1])
                    if value is not None:
                        return value
            value = _first_number(line)
            if value is not None:
                return value

    match = re.search(r"(?:avg|average)\s*[=:]\s*([\d.]+)", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def parse_player_count(response: str) -> int:
    import re
    match = re.search(r"There are (\d+) of a max of", response)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)\s+online", response)
    if match:
        return int(match.group(1))
    parts = response.split("/")
    if len(parts) >= 2:
        try:
            return int(parts[0].strip().split()[-1])
        except (ValueError, IndexError):
            pass
    return 0
