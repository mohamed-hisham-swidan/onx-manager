from __future__ import annotations

from typing import Any

from app.core.event_bus import DomainEvent


class BackupStartedEvent(DomainEvent):
    backup_id: str
    server_id: str
    tier: str = "tier_1"

    def __init__(self, backup_id: str, server_id: str, **data: Any) -> None:
        super().__init__(backup_id=backup_id, server_id=server_id, **data)  # type: ignore[call-arg]


class BackupCompletedEvent(DomainEvent):
    backup_id: str
    server_id: str
    size_bytes: int
    checksum: str
    storage_path: str = ""
    tier: str = "tier_1"

    def __init__(
        self, backup_id: str, server_id: str, size_bytes: int, checksum: str, **data: Any
    ) -> None:
        payload = {
            "backup_id": backup_id,
            "server_id": server_id,
            "size_bytes": size_bytes,
            "checksum": checksum,
            **data,
        }
        super().__init__(**payload)


class BackupFailedEvent(DomainEvent):
    backup_id: str
    server_id: str
    reason: str
    tier: str = "tier_1"

    def __init__(self, backup_id: str, server_id: str, reason: str, **data: Any) -> None:
        super().__init__(backup_id=backup_id, server_id=server_id, reason=reason, **data)  # type: ignore[call-arg]


class BackupRestoredEvent(DomainEvent):
    backup_id: str
    server_id: str
    tier: str = "tier_1"

    def __init__(self, backup_id: str, server_id: str, **data: Any) -> None:
        super().__init__(backup_id=backup_id, server_id=server_id, **data)  # type: ignore[call-arg]


class BackupDeletedEvent(DomainEvent):
    backup_id: str
    server_id: str
    tier: str = "tier_1"

    def __init__(self, backup_id: str, server_id: str, **data: Any) -> None:
        super().__init__(backup_id=backup_id, server_id=server_id, **data)  # type: ignore[call-arg]
