from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.operations.domain.aggregate import Operation


class OperationRepository(ABC):
    @abstractmethod
    async def save(self, operation: Operation) -> Operation:
        """Persist or update an operation and its steps."""
        ...

    @abstractmethod
    async def get(self, operation_id: str) -> Operation | None:
        """Fetch operation by id including all steps."""
        ...

    @abstractmethod
    async def get_by_idempotency_key(
        self,
        target_type: str,
        target_id: str | None,
        idempotency_key: str,
    ) -> Operation | None:
        """Fetch operation by unique (target_type, target_id, idempotency_key)."""
        ...

    @abstractmethod
    async def get_active_for_target(
        self,
        target_type: str,
        target_id: str,
    ) -> list[Operation]:
        """Fetch all operations currently in active states
        (QUEUED, PREPARING, RUNNING, CANCEL_REQUESTED).
        """
        ...

    @abstractmethod
    async def list_operations(
        self,
        target_type: str | None = None,
        target_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Operation]:
        """List operations with optional filtering ordered by created_at DESC."""
        ...

    @abstractmethod
    async def atomic_request_cancellation(self, operation_id: str) -> bool:
        """Atomically transition status to CANCEL_REQUESTED if in QUEUED, PREPARING, RUNNING.
        Returns True if row was updated (won the race), False otherwise.
        """
        ...

    @abstractmethod
    async def atomic_timeout(self, operation_id: str) -> bool:
        """Atomically transition status to TIMED_OUT if in PREPARING or RUNNING
        and cancellation not requested.
        Returns True if row was updated (won the race), False otherwise.
        """
        ...
