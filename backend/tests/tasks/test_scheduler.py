import pytest

from app.tasks.scheduler import Scheduler
from app.tasks.base import TaskQueue, TaskStatus


class FakeSessionFactory:
    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    async def __call__(self) -> "FakeSessionFactory":
        return self

    async def __aenter__(self) -> "FakeSessionFactory":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def get(self, model: type, pk: str) -> object | None:
        return self._store.get(pk)

    async def execute(self, stmt: object) -> object:
        from unittest.mock import MagicMock
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result

    def add(self, obj: object) -> None:
        if hasattr(obj, "id"):
            self._store[obj.id] = obj

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass


class FakeQueue(TaskQueue):
    async def enqueue(self, name: str, params: dict | None = None, delay: int = 0) -> str:
        return "tid"

    async def cancel(self, task_id: str) -> bool:
        return True

    async def get_status(self, task_id: str) -> TaskStatus:
        return TaskStatus.PENDING

    async def get_result(self, task_id: str) -> object:
        return None


@pytest.mark.asyncio
async def test_scheduler_create_and_stop() -> None:
    factory = FakeSessionFactory()
    scheduler = Scheduler(factory)
    assert scheduler._running is False

    await scheduler.start()
    assert scheduler._running is True
    assert scheduler._aps is not None

    await scheduler.stop()
    assert scheduler._running is False


@pytest.mark.asyncio
async def test_scheduler_set_task_queue() -> None:
    factory = FakeSessionFactory()
    scheduler = Scheduler(factory)
    queue = FakeQueue()
    scheduler.set_task_queue(queue)
    assert scheduler._task_queue is queue
