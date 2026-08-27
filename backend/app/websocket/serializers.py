from __future__ import annotations

import json
from typing import Any

from app.core.event_bus import DomainEvent

MAX_MESSAGE_SIZE = 256 * 1024


class WSMessage:
    __slots__ = ("type", "data", "channel")

    def __init__(
        self, type: str, data: dict[str, Any] | None = None, channel: str | None = None
    ) -> None:
        self.type = type
        self.data = data or {}
        self.channel = channel

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type}
        payload.update(self.data)
        return payload

    def to_json(self) -> bytes:
        raw = json.dumps(self.to_dict(), ensure_ascii=False, default=str).encode("utf-8")
        if len(raw) > MAX_MESSAGE_SIZE:
            raise ValueError(f"Message exceeds maximum size of {MAX_MESSAGE_SIZE} bytes")
        return raw


class MessageSerializer:
    @staticmethod
    def serialize(message: WSMessage) -> bytes:
        return message.to_json()

    @staticmethod
    def deserialize(raw: str | bytes) -> dict[str, Any]:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if len(raw) > MAX_MESSAGE_SIZE:
            raise ValueError(f"Message exceeds maximum size of {MAX_MESSAGE_SIZE} bytes")
        return json.loads(raw)

    @staticmethod
    def event_to_message(event: DomainEvent, channel: str | None = None) -> WSMessage:
        data = (
            event.model_dump()
            if hasattr(event, "model_dump")
            else {"event_type": type(event).__name__}
        )
        serialized: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, (float, str, int, bool, dict, list)):
                serialized[key] = value
            elif value is None:
                serialized[key] = None
            else:
                serialized[key] = str(value)
        msg = WSMessage(
            type="event",
            data={"event": serialized},
            channel=channel,
        )
        return msg

    @staticmethod
    def state_message(server_id: str, status: dict[str, Any]) -> WSMessage:
        return WSMessage(
            type="state",
            data={"server_id": server_id, "status": status},
        )

    @staticmethod
    def metrics_message(server_id: str, tps: float, players: int, ram_mb: int) -> WSMessage:
        return WSMessage(
            type="metrics",
            data={"server_id": server_id, "tps": tps, "players": players, "ram_mb": ram_mb},
        )

    @staticmethod
    def metrics_batch_message(server_id: str, samples: list[dict[str, Any]]) -> WSMessage:
        return WSMessage(
            type="metrics_batch",
            data={"server_id": server_id, "samples": samples},
        )

    @staticmethod
    def state_sync_message(events: list[dict[str, Any]]) -> WSMessage:
        return WSMessage(
            type="state_sync",
            data={"events": events},
        )

    @staticmethod
    def error_message(code: str, message: str) -> WSMessage:
        return WSMessage(
            type="error",
            data={"code": code, "message": message},
        )

    @staticmethod
    def auth_expired_message() -> WSMessage:
        return WSMessage(
            type="auth_expired",
            data={},
        )

    @staticmethod
    def pong_message() -> WSMessage:
        return WSMessage(
            type="pong",
            data={},
        )
