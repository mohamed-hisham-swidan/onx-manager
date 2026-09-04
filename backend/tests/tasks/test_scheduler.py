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


@pytest.mark.asyncio
async def test_scheduler_survives_restart_and_reconciles_from_db(tmp_path) -> None:
    """ISS-034: Scheduled jobs persist in DB and are reconciled/re-registered on reboot."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.persistence.base import Base

    db_file = tmp_path / "scheduler_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async_session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _session_factory():
        return async_session()

    # 1. Initial process lifecycle: instantiate and start scheduler
    scheduler1 = Scheduler(_session_factory)
    queue1 = FakeQueue()
    scheduler1.set_task_queue(queue1)
    await scheduler1.start()

    # Add a job (persists to DB and registers in APScheduler)
    await scheduler1.add_job(
        name="daily_server_backup",
        cron_expression="0 3 * * *",
        task_name="run_backup_task",
        params={"server_id": "srv-123"},
    )

    jobs1 = scheduler1._aps.get_jobs()
    assert len(jobs1) == 1

    # 2. Simulate process shutdown (scheduler stops, in-memory APScheduler destroyed)
    await scheduler1.stop()
    assert scheduler1._running is False

    # 3. Simulate process restart: fresh Scheduler instance using same DB
    scheduler2 = Scheduler(_session_factory)
    queue2 = FakeQueue()
    scheduler2.set_task_queue(queue2)
    assert scheduler2._aps is None  # Nothing in memory before start

    # On boot, scheduler.start() calls _load_jobs() from DB and schedules them
    await scheduler2.start()
    assert scheduler2._running is True
    assert scheduler2._aps is not None

    # Verify job survived restart and is active in APScheduler
    jobs2 = scheduler2._aps.get_jobs()
    assert len(jobs2) == 1
    assert jobs2[0].id == jobs1[0].id
    assert jobs2[0].misfire_grace_time == 60
    assert jobs2[0].max_instances == 1
    assert jobs2[0].coalesce is True

    await scheduler2.stop()
    await engine.dispose()


@pytest.mark.asyncio
async def test_scheduler_last_run_at_update_failure_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ISS-033: Failure to update last_run_at in DB should log a warning, not silently pass."""
    import logging

    from app.tasks.scheduler import CronJobModel

    caplog.set_level(logging.WARNING)

    class FailingSessionFactory(FakeSessionFactory):
        async def commit(self) -> None:
            raise RuntimeError("DB disk full on commit")

    factory = FailingSessionFactory()
    scheduler = Scheduler(factory)
    queue = FakeQueue()
    scheduler.set_task_queue(queue)
    await scheduler.start()

    from datetime import UTC, datetime

    model = CronJobModel(
        id="job-fail-test",
        name="test_failing_job",
        cron_expression="* * * * *",
        task_name="test_task",
        params_json="{}",
        enabled=1,
        created_at=datetime.now(UTC),
    )
    factory.add(model)
    scheduler._schedule_job(model)

    # Trigger job function directly
    job = scheduler._aps.get_job("job-fail-test")
    assert job is not None
    await job.func()

    assert any(
        "Failed to update last_run_at for job job-fail-test" in record.message
        for record in caplog.records
    )

    await scheduler.stop()
