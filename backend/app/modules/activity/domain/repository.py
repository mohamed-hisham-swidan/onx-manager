from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.activity.domain.entities import ServerActivityLog


class ActivityRepository(ABC):
    """Abstract interface for storing and querying server activity logs."""

    @abstractmethod
    async def save(self, log: ServerActivityLog) -> None:
        """Persists a new activity log entry."""
        ...

    @abstractmethod
    async def list_by_server(
        self,
        server_id: str,
        limit: int = 50,
        offset: int = 0,
        event_type: str | None = None,
        from_date: float | None = None,
        to_date: float | None = None,
    ) -> tuple[list[ServerActivityLog], int]:
        """Returns paginated activity logs for a server matching criteria and total count."""
        ...

    @abstractmethod
    async def delete_older_than(self, cutoff_timestamp: float) -> int:
        """Deletes activity logs older than cutoff timestamp, returning deleted count."""
        ...
