import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tasks.base import TaskQueue, TaskStatus
from app.tasks.queue import InProcessQueue, TaskModel


class FakeSession:
    def __init__(self) -> None:
        self._store: dict[str, object] = {}
        self._committed = False

    async def get(self, _model_class: type, pk: object) -> object | None:
        for obj in self._store.values():
            if getattr(obj, "task_id", None) == pk:
                return obj
        return None

    async def execute(self, _stmt: object) -> MagicMock:
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
        async def enqueue(self, _name: str, _params: dict | None = None, _delay: int = 0) -> str:
            return "tid"

        async def cancel(self, _task_id: str) -> bool:
            return True

        async def get_status(self, _task_id: str) -> TaskStatus:
            return TaskStatus.PENDING

        async def get_result(self, _task_id: str) -> object:
            return None

    queue = TestQueue()
    assert await queue.enqueue("x") == "tid"
    assert await queue.cancel("x")
    assert await queue.get_status("x") == TaskStatus.PENDING
    assert await queue.get_result("x") is None


class ReclaimSession:
    """Fake session that persists TaskModel mutations and reports rowcount on updates."""

    def __init__(self) -> None:
        self._store: dict[str, TaskModel] = {}
        self._update_rowcount: int = 0

    def seed(self, model: TaskModel) -> None:
        self._store[model.task_id] = model

    async def get(self, _model_class: type, pk: object) -> object | None:
        return self._store.get(pk)

    async def execute(self, stmt: object) -> MagicMock:
        result = MagicMock()
        if hasattr(stmt, "values"):
            result.rowcount = self._update_rowcount
        else:
            result.scalars.return_value.all.return_value = [
                m for m in self._store.values() if m.status == TaskStatus.PENDING
            ]
        return result

    def set_update_rowcount(self, count: int) -> None:
        self._update_rowcount = count

    async def commit(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def __aenter__(self) -> "ReclaimSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


def _task(
    task_id: str,
    name: str,
    status: TaskStatus,
    started_at: datetime | None = None,
) -> TaskModel:
    return TaskModel(
        task_id=task_id,
        name=name,
        params_json="{}",
        status=status,
        started_at=started_at,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_reclaim_pending_reports_unregistered_and_skips_claim_failure() -> None:
    session = ReclaimSession()
    session.seed(_task("t-registered", "registered_task", TaskStatus.PENDING))
    session.seed(_task("t-unregistered", "unknown_task", TaskStatus.PENDING))
    session.set_update_rowcount(0)  # claim never succeeds -> nothing dispatched

    async def factory() -> ReclaimSession:
        return session

    queue = InProcessQueue(factory)
    queue.register("registered_task", AsyncMock(return_value={"ok": True}))

    result = await queue.reclaim_pending()

    assert result["reclaimed"] == 0
    assert result["skipped_unregistered"] == 1
    assert result["errors"] == 0


@pytest.mark.asyncio
async def test_reclaim_pending_dispatches_registered_task() -> None:
    session = ReclaimSession()
    session.seed(_task("t-registered-2", "registered_task", TaskStatus.PENDING))
    session.set_update_rowcount(1)  # claim succeeds for the single PENDING row

    async def factory() -> ReclaimSession:
        return session

    queue = InProcessQueue(factory)
    queue.register("registered_task", AsyncMock(return_value={"ok": True}))

    result = await queue.reclaim_pending()
    await asyncio.sleep(0.05)  # let the dispatched _execute complete
    assert result["reclaimed"] == 1
    assert result["skipped_unregistered"] == 0
    assert result["errors"] == 0
    assert session._store["t-registered-2"].status == TaskStatus.SUCCESS


@pytest.mark.asyncio
async def test_mark_stale_running_failed_returns_rowcount() -> None:
    session = ReclaimSession()
    session.set_update_rowcount(2)

    async def factory() -> ReclaimSession:
        return session

    queue = InProcessQueue(factory)
    count = await queue.mark_stale_running_failed(max_age_minutes=30)
    assert count == 2


@pytest.mark.asyncio
async def test_delayed_task_survives_gc_and_executes() -> None:
    """ISS-032: Delayed tasks must not be garbage collected and must execute after delay."""
    import gc

    session = FakeSession()

    async def get_session() -> FakeSession:
        return session

    queue = InProcessQueue(get_session)
    executed = asyncio.Event()

    async def my_handler(_params: dict) -> dict:
        executed.set()
        return {"result": "done"}

    queue.register("delayed_op", my_handler)

    task_id = await queue.enqueue("delayed_op", {"foo": "bar"}, delay=0.05)

    # Force aggressive garbage collection multiple times while task is sleeping
    gc.collect()
    gc.collect()

    # Wait for the delayed task to execute
    await asyncio.wait_for(executed.wait(), timeout=1.0)

    # Allow session commits inside _execute to complete
    await asyncio.sleep(0.05)
    model = await session.get(TaskModel, task_id)
    assert model is not None
    assert model.status == TaskStatus.SUCCESS


@pytest.mark.asyncio
async def test_task_handler_exception_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """ISS-032: Handler exceptions must be logged and not silently swallowed."""
    import logging

    caplog.set_level(logging.ERROR)
    session = FakeSession()

    async def get_session() -> FakeSession:
        return session

    queue = InProcessQueue(get_session)
    done_event = asyncio.Event()

    async def failing_handler(_params: dict) -> None:
        try:
            raise ValueError("kaboom failure in handler")
        finally:
            done_event.set()

    queue.register("fail_op", failing_handler)
    task_id = await queue.enqueue("fail_op", {}, delay=0)

    await asyncio.wait_for(done_event.wait(), timeout=1.0)
    await asyncio.sleep(0.05)

    model = await session.get(TaskModel, task_id)
    assert model is not None
    assert model.status == TaskStatus.FAILED
    assert "ValueError: kaboom failure in handler" in (model.error or "")

    # Assert exception was logged
    assert any(
        "fail_op" in record.message or "kaboom failure" in str(record.exc_info)
        for record in caplog.records
    )

