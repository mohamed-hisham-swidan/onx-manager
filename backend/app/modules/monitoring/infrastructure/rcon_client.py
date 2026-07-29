from __future__ import annotations

import asyncio
import contextlib
import logging
import struct

logger = logging.getLogger(__name__)

PACKET_LOGIN = 3
PACKET_COMMAND = 2
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
        _, ptype, body = await self._read_packet()
        if ptype == PACKET_RESPONSE and body == "":
            return
        raise AuthenticationError("RCON authentication failed")

    async def send_command(self, command: str) -> str:
        self._request_id += 1
        req_id = self._request_id
        await self._send_packet(req_id, PACKET_COMMAND, command)
        _, _, body = await self._read_packet()
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


def parse_tps(response: str) -> float | None:
    for line in response.splitlines():
        line = line.strip()
        if line.startswith("TPS from last"):
            parts = line.split(", ")
            if parts:
                last = parts[-1].strip()
                try:
                    return float(last)
                except ValueError:
                    pass
        elif "Overall TPS" in line or "§e" in line:
            import re
            match = re.search(r"(\d+\.?\d*)", line.replace("§e", "").replace("§6", ""))
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    pass

    import re
    match = re.search(r"avg\s*[=:]\s*([\d.]+)", response)
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
