from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class TaskStatus(IntEnum):
    PENDING = 0
    RUNNING = 1
    SUCCESS = 2
    FAILED = 3
    CANCELLED = 4


@dataclass
class TaskResult:
    task_id: str
    name: str
    status: TaskStatus
    result: Any = None
    error: str | None = None


class TaskQueue(ABC):
    @abstractmethod
    async def enqueue(
        self, name: str, params: dict[str, Any] | None = None, delay: int = 0
    ) -> str: ...

    @abstractmethod
    async def cancel(self, task_id: str) -> bool: ...

    @abstractmethod
    async def get_status(self, task_id: str) -> TaskStatus: ...

    @abstractmethod
    async def get_result(self, task_id: str) -> Any: ...
