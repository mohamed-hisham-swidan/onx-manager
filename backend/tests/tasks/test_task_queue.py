import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks.base import TaskQueue, TaskStatus
from app.tasks.queue import InProcessQueue, TaskModel


class FakeSession:
    def __init__(self) -> None:
        self._store: dict[str, object] = {}
        self._committed = False

    async def get(self, model_class: type, pk: object) -> object | None:
        for obj in self._store.values():
            if getattr(obj, "task_id", None) == pk:
                return obj
        return None

    async def execute(self, stmt: object) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.all.return_value = list(self._store.values())
        return result

    def add(self, obj: object) -> None:
        if isinstance(obj, TaskModel) and obj.task_id:
            self._store[obj.task_id] = obj

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self._committed = True

    async def close(self) -> None:
        pass

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


async def fake_session_factory() -> FakeSession:
    return FakeSession()


@pytest.mark.asyncio
async def test_enqueue_returns_task_id() -> None:
    queue = InProcessQueue(lambda: fake_session_factory())
    task_id = await queue.enqueue("test_task", {"key": "value"})
    assert isinstance(task_id, str)
    assert len(task_id) > 0


@pytest.mark.asyncio
async def test_cancel_pending_task() -> None:
    session = FakeSession()

    async def get_session() -> FakeSession:
        return session

    queue = InProcessQueue(get_session)
    task_id = await queue.enqueue("test_task", {"x": 1})
    assert await queue.cancel(task_id)


@pytest.mark.asyncio
async def test_get_status_unknown_task() -> None:
    queue = InProcessQueue(lambda: fake_session_factory())
    status = await queue.get_status("nonexistent")
    assert status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_get_result_not_found() -> None:
    queue = InProcessQueue(lambda: fake_session_factory())
    result = await queue.get_result("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_cancel_nonexistent_task() -> None:
    queue = InProcessQueue(lambda: fake_session_factory())
    assert not await queue.cancel("nonexistent")


@pytest.mark.asyncio
async def test_interface_contract() -> None:
    class TestQueue(TaskQueue):
        async def enqueue(self, name: str, params: dict | None = None, delay: int = 0) -> str:
            return "tid"

        async def cancel(self, task_id: str) -> bool:
            return True

        async def get_status(self, task_id: str) -> TaskStatus:
            return TaskStatus.PENDING

        async def get_result(self, task_id: str) -> object:
            return None

    queue = TestQueue()
    assert await queue.enqueue("x") == "tid"
    assert await queue.cancel("x")
    assert await queue.get_status("x") == TaskStatus.PENDING
    assert await queue.get_result("x") is None
