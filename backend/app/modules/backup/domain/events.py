from __future__ import annotations

from typing import Any

from app.core.event_bus import DomainEvent


class BackupStartedEvent(DomainEvent):
    backup_id: str
    server_id: str

    def __init__(self, backup_id: str, server_id: str, **data: Any) -> None:
        super().__init__(backup_id=backup_id, server_id=server_id, **data)


class BackupCompletedEvent(DomainEvent):
    backup_id: str
    server_id: str
    size_bytes: int
    checksum: str
    storage_path: str = ""

    def __init__(self, backup_id: str, server_id: str, size_bytes: int, checksum: str, **data: Any) -> None:
        super().__init__(backup_id=backup_id, server_id=server_id, size_bytes=size_bytes, checksum=checksum, **data)


class BackupFailedEvent(DomainEvent):
    backup_id: str
    server_id: str
    reason: str

    def __init__(self, backup_id: str, server_id: str, reason: str, **data: Any) -> None:
        super().__init__(backup_id=backup_id, server_id=server_id, reason=reason, **data)


class BackupRestoredEvent(DomainEvent):
    backup_id: str
    server_id: str

    def __init__(self, backup_id: str, server_id: str, **data: Any) -> None:
        super().__init__(backup_id=backup_id, server_id=server_id, **data)


class BackupDeletedEvent(DomainEvent):
    backup_id: str
    server_id: str

    def __init__(self, backup_id: str, server_id: str, **data: Any) -> None:
        super().__init__(backup_id=backup_id, server_id=server_id, **data)
