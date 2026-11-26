"""Pure-Python Minecraft Server List Ping (SLP) probe helper.

Implements the standard Minecraft Status Ping protocol (VarInt framing,
Handshake packet 0x00 with next_state=1, Status Request 0x00, JSON status
response, and Ping 0x01 / Pong 0x01 RTT) using only the Python standard
library. Works across Minecraft 1.7 through 1.21.11 and 26.x, Vanilla,
Paper, Purpur, Fabric, Forge, NeoForge, and proxies, regardless of
``online-mode``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import struct
import time
from dataclasses import dataclass
from typing import Any

DEFAULT_SLP_TIMEOUT_SECONDS = 4.0
DEFAULT_SLP_PROTOCOL_VERSION = -1
MAX_SLP_PACKET_BYTES = 1024 * 1024


@dataclass(frozen=True)
class SlpProbeResult:
    """Structured result of a Minecraft Server List Ping probe."""

    reachable: bool
    latency_ms: int | None = None
    version_name: str | None = None
    protocol_version: int | None = None
    players_online: int | None = None
    players_max: int | None = None
    motd: str | None = None
    error: str | None = None


def _encode_varint(value: int) -> bytes:
    """Encode a 32-bit signed integer as a Minecraft VarInt."""
    uval = value & 0xFFFFFFFF
    out = bytearray()
    while True:
        byte = uval & 0x7F
        uval >>= 7
        if uval:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


async def _read_varint(reader: asyncio.StreamReader) -> int:
    """Read a Minecraft VarInt (up to 5 bytes) from *reader*."""
    result = 0
    for shift in range(0, 35, 7):
        raw = await reader.readexactly(1)
        byte = raw[0]
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            if result & 0x80000000:
                result -= 0x100000000
            return result
    raise ValueError("VarInt is too big")


def _pack_packet(packet_id: int, payload: bytes = b"") -> bytes:
    body = _encode_varint(packet_id) + payload
    return _encode_varint(len(body)) + body


def _extract_motd(description: Any) -> str | None:
    if isinstance(description, str):
        return description.strip() or None
    if isinstance(description, dict):
        parts: list[str] = []
        text = description.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
        extra = description.get("extra")
        if isinstance(extra, list):
            for item in extra:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
        joined = "".join(parts).strip()
        return joined or None
    return None


def slp_version_matches_mc(version_name: str | None, target_mc: str) -> bool:
    """Return True if *version_name* reports *target_mc* as a version token.

    Handles values such as ``"Purpur 1.21.11"``, ``"Paper 1.21.11"``,
    ``"1.21.11"``, ``"1.21.11-R0.1"``, and ``"26.3"``, while rejecting
    partial prefix matches like ``"Purpur 1.21.1"`` against ``"1.21.11"``.
    """
    if not version_name or not target_mc:
        return False
    target = target_mc.strip()
    if not target:
        return False
    pattern = rf"(?<![0-9.]){re.escape(target)}(?![0-9])"
    return bool(re.search(pattern, version_name.strip()))


async def probe_minecraft_slp(
    host: str,
    port: int = 25565,
    *,
    timeout_seconds: float = DEFAULT_SLP_TIMEOUT_SECONDS,
    protocol_version: int = DEFAULT_SLP_PROTOCOL_VERSION,
) -> SlpProbeResult:
    """Perform a bounded Minecraft SLP status + ping/pong probe."""
    writer: asyncio.StreamWriter | None = None

    async def _exchange() -> SlpProbeResult:
        nonlocal writer
        connect_start = time.monotonic()
        reader, writer = await asyncio.open_connection(host, int(port))

        host_bytes = host.encode("utf-8")
        handshake_payload = (
            _encode_varint(protocol_version)
            + _encode_varint(len(host_bytes))
            + host_bytes
            + struct.pack(">H", int(port) & 0xFFFF)
            + _encode_varint(1)  # next_state = Status
        )
        writer.write(_pack_packet(0x00, handshake_payload))
        writer.write(_pack_packet(0x00))  # Status Request
        await writer.drain()

        packet_len = await _read_varint(reader)
        if packet_len <= 0 or packet_len > MAX_SLP_PACKET_BYTES:
            raise ValueError(f"Invalid SLP status packet length: {packet_len}")
        packet_id = await _read_varint(reader)
        if packet_id != 0x00:
            raise ValueError(f"Unexpected SLP status packet id: {packet_id}")
        json_len = await _read_varint(reader)
        if json_len < 0 or json_len > MAX_SLP_PACKET_BYTES:
            raise ValueError(f"Invalid SLP JSON length: {json_len}")
        raw_json = await reader.readexactly(json_len)
        status_rtt_ms = max(0, int(round((time.monotonic() - connect_start) * 1000)))

        payload = json.loads(raw_json.decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            raise ValueError("SLP status response was not a JSON object")

        version_obj = payload.get("version") if isinstance(payload.get("version"), dict) else {}
        players_obj = payload.get("players") if isinstance(payload.get("players"), dict) else {}

        version_name = (
            str(version_obj["name"]).strip()
            if isinstance(version_obj.get("name"), str) and version_obj["name"].strip()
            else None
        )
        proto_val = version_obj.get("protocol")
        parsed_proto = (
            proto_val if isinstance(proto_val, int) and not isinstance(proto_val, bool) else None
        )
        players_online = (
            players_obj["online"]
            if isinstance(players_obj.get("online"), int)
            and not isinstance(players_obj.get("online"), bool)
            else None
        )
        players_max = (
            players_obj["max"]
            if isinstance(players_obj.get("max"), int)
            and not isinstance(players_obj.get("max"), bool)
            else None
        )
        motd = _extract_motd(payload.get("description"))

        # Optional Ping (0x01) / Pong (0x01) for accurate RTT
        latency_ms = status_rtt_ms
        try:
            ping_token = int(time.time() * 1000) & 0x7FFFFFFFFFFFFFFF
            ping_start = time.monotonic()
            writer.write(_pack_packet(0x01, struct.pack(">q", ping_token)))
            await writer.drain()
            pong_len = await _read_varint(reader)
            if 0 < pong_len <= 64:
                pong_id = await _read_varint(reader)
                if pong_id == 0x01:
                    await reader.readexactly(8)
                    latency_ms = max(0, int(round((time.monotonic() - ping_start) * 1000)))
        except Exception:
            # Keep status RTT if the server closed the socket after status response.
            pass

        return SlpProbeResult(
            reachable=True,
            latency_ms=latency_ms,
            version_name=version_name,
            protocol_version=parsed_proto,
            players_online=players_online,
            players_max=players_max,
            motd=motd,
        )

    try:
        return await asyncio.wait_for(_exchange(), timeout=float(timeout_seconds))
    except TimeoutError:
        return SlpProbeResult(
            reachable=False,
            error=f"SLP probe to {host}:{port} timed out after {timeout_seconds:.1f}s",
        )
    except Exception as exc:
        return SlpProbeResult(
            reachable=False,
            error=f"SLP probe to {host}:{port} failed: {exc}",
        )
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


__all__ = [
    "DEFAULT_SLP_PROTOCOL_VERSION",
    "DEFAULT_SLP_TIMEOUT_SECONDS",
    "SlpProbeResult",
    "probe_minecraft_slp",
    "slp_version_matches_mc",
]
