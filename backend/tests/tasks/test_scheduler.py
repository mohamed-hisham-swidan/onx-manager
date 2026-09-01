import pytest

from app.modules.auth.infrastructure.models import UserModel  # noqa: F401
from app.modules.server.infrastructure.models import ServerModel  # noqa: F401
from app.tasks.base import TaskQueue, TaskStatus
from app.tasks.scheduler import Scheduler


class FakeSessionFactory:
    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    async def __call__(self) -> "FakeSessionFactory":
        return self

    async def __aenter__(self) -> "FakeSessionFactory":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def get(self, _model: type, pk: str) -> object | None:
        return self._store.get(pk)

    async def execute(self, _stmt: object) -> object:
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
    async def enqueue(self, _name: str, _params: dict | None = None, _delay: int = 0) -> str:
        return "tid"

    async def cancel(self, _task_id: str) -> bool:
        return True

    async def get_status(self, _task_id: str) -> TaskStatus:
        return TaskStatus.PENDING

    async def get_result(self, _task_id: str) -> object:
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


@pytest.mark.asyncio
async def test_scheduler_add_interval_and_cron_job() -> None:
    factory = FakeSessionFactory()
    scheduler = Scheduler(factory)
    queue = FakeQueue()
    scheduler.set_task_queue(queue)
    await scheduler.start()

    await scheduler.add_job(
        name="test_interval_job",
        cron_expression="interval:0.2s",
        task_name="run_metrics_collection",
    )

    await scheduler.add_job(
        name="test_cron_job",
        cron_expression="0 * * * *",
        task_name="run_backup_task",
    )

    assert scheduler._aps is not None
    assert len(scheduler._aps.get_jobs()) == 2

    # Verify misfire_grace_time is 60 on all scheduled jobs
    for job in scheduler._aps.get_jobs():
        assert job.misfire_grace_time == 60

    await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_misfire_grace_time_allows_delayed_job() -> None:
    """Verify jobs with misfire_grace_time=60 absorb delays > 1s without misfiring."""
    factory = FakeSessionFactory()
    scheduler = Scheduler(factory)
    queue = FakeQueue()
    scheduler.set_task_queue(queue)
    await scheduler.start()

    await scheduler.add_job(
        name="test_grace_job",
        cron_expression="0 * * * *",
        task_name="run_backup_task",
    )

    job = scheduler._aps.get_job(list(factory._store.keys())[0])
    assert job is not None
    assert job.misfire_grace_time == 60
    assert job.coalesce is True
    assert job.max_instances == 1

    await scheduler.stop()
