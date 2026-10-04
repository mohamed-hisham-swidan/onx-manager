from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.core.event_bus import DomainEvent
from app.core.timeutil import (
    NAIVE_ISO_REGEX,
    format_datetime_utc,
    is_timestamp_field,
)

MAX_MESSAGE_SIZE = 256 * 1024


def _ws_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return format_datetime_utc(obj)
    return str(obj)


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
        raw = json.dumps(self.to_dict(), ensure_ascii=False, default=_ws_default).encode("utf-8")
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
            if isinstance(value, datetime):
                serialized[key] = format_datetime_utc(value)
            elif (
                isinstance(value, str)
                and is_timestamp_field(key)
                and NAIVE_ISO_REGEX.match(value)
            ):
                serialized[key] = value.replace(" ", "T") + "Z"
            elif isinstance(value, (float, str, int, bool, dict, list)):
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

    @staticmethod
    def console_message(server_id: str, lines: list[str]) -> WSMessage:
        return WSMessage(
            type="console",
            data={"server_id": server_id, "lines": lines},
            channel=f"server:{server_id}:console",
        )

    @staticmethod
    def test_console_message(test_id: str, lines: list[str]) -> WSMessage:
        return WSMessage(
            type="console",
            data={"test_id": test_id, "lines": lines},
            channel=f"test:{test_id}:console",
        )

    @staticmethod
    def exec_result_message(
        target_id: str,
        target_type: str,
        output: str,
        exit_code: int = 0,
    ) -> WSMessage:
        return WSMessage(
            type="exec_result",
            data={
                "target_id": target_id,
                "target_type": target_type,
                "output": output,
                "exit_code": exit_code,
            },
        )
