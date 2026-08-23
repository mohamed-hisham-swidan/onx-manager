from __future__ import annotations

from typing import Any

from app.core.event_bus import DomainEvent
from app.modules.shared.value_objects import ServerId


class ServerCreatedEvent(DomainEvent):
    server_id: str
    name: str
    minecraft_version: str

    def __init__(self, server_id: ServerId, name: str, minecraft_version: str, **data: Any) -> None:
        super().__init__(
            server_id=str(server_id),
            name=name,
            minecraft_version=minecraft_version,
            **data,
        )


class ServerStartingEvent(DomainEvent):
    server_id: str

    def __init__(self, server_id: ServerId, **data: Any) -> None:
        super().__init__(server_id=str(server_id), **data)


class ServerStartedEvent(DomainEvent):
    server_id: str
    pid: int
    port: int

    def __init__(self, server_id: ServerId, pid: int, port: int, **data: Any) -> None:
        super().__init__(server_id=str(server_id), pid=pid, port=port, **data)


class ServerStoppingEvent(DomainEvent):
    server_id: str
    reason: str = ""

    def __init__(self, server_id: ServerId, reason: str = "", **data: Any) -> None:
        super().__init__(server_id=str(server_id), reason=reason, **data)


class ServerStoppedEvent(DomainEvent):
    server_id: str

    def __init__(self, server_id: ServerId, **data: Any) -> None:
        super().__init__(server_id=str(server_id), **data)


class ServerCrashedEvent(DomainEvent):
    server_id: str
    exit_code: int
    last_log_lines: list[str]

    def __init__(self, server_id: ServerId, exit_code: int, last_log_lines: list[str] | None = None, **data: Any) -> None:
        super().__init__(
            server_id=str(server_id),
            exit_code=exit_code,
            last_log_lines=last_log_lines or [],
            **data,
        )


class ServerConfigChangedEvent(DomainEvent):
    server_id: str
    changed_keys: list[str]

    def __init__(self, server_id: ServerId, changed_keys: list[str], **data: Any) -> None:
        super().__init__(server_id=str(server_id), changed_keys=changed_keys, **data)


class ServerDeletedEvent(DomainEvent):
    server_id: str

    def __init__(self, server_id: ServerId, **data: Any) -> None:
        super().__init__(server_id=str(server_id), **data)


class ServerDiscoveredEvent(DomainEvent):
    path: str
    detected_type: str
    metadata: dict[str, Any]

    def __init__(self, path: str, detected_type: str = "unknown", metadata: dict[str, Any] | None = None, **data: Any) -> None:
        super().__init__(path=path, detected_type=detected_type, metadata=metadata or {}, **data)


class ServerVanishedEvent(DomainEvent):
    path: str

    def __init__(self, path: str, **data: Any) -> None:
        super().__init__(path=path, **data)


class ForgeProvisionProgressEvent(DomainEvent):
    server_id: str
    stage: str
    percent: int | None
    message: str

    def __init__(
        self,
        server_id: ServerId,
        stage: str,
        percent: int | None,
        message: str,
        **data: Any,
    ) -> None:
        super().__init__(
            server_id=str(server_id),
            stage=stage,
            percent=percent,
            message=message,
            **data,
        )
