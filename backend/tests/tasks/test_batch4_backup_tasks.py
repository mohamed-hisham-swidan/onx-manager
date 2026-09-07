from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.backup.application.commands.create_backup import CreateBackupCommand
from app.modules.backup.application.restore_service import _atomic_replace_dir
from app.modules.exposure.application.commands import SetServerExposureCommand
from app.modules.server.application.commands.create_server import CreateServerCommand
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.modules.storage.s3 import S3Storage
from app.services.backup_orchestrator import BackupSaga
from app.tasks.base import TaskStatus
from app.tasks.definitions.cleanup_task import run_cleanup_task
from app.tasks.definitions.discovery_scan import periodic_discovery_scan
from app.tasks.definitions.health_check_task import run_health_check_task
from app.tasks.definitions.metrics_collector import init_collector, run_metrics_collection_task
from app.tasks.queue import InProcessQueue


@pytest.fixture(autouse=True)
async def init_db():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.modules.auth.infrastructure.audit  # noqa: F401
    import app.modules.server.infrastructure.models  # noqa: F401
    import app.tasks.queue  # noqa: F401
    from app.core.persistence.base import Base
    from app.core.persistence.db import database

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS idempotency_keys "
                "(key TEXT PRIMARY KEY, created_at TIMESTAMP)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS event_store "
                "(id INTEGER PRIMARY KEY, created_at TIMESTAMP)"
            )
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine = database._engine
    old_factory = database._session_factory
    database._engine = engine
    database._session_factory = session_factory
    yield
    database._engine = old_engine
    database._session_factory = old_factory
    await engine.dispose()


class TestBatch4BS3Storage:
    """F023: S3Storage.exists distinguishes 404 NoSuchKey from real errors."""

    @pytest.mark.asyncio
    async def test_exists_returns_false_on_404(self) -> None:
        client = AsyncMock()
        error_resp = {"Error": {"Code": "404", "Message": "Not Found"}}
        err = Exception("Not found")
        err.response = error_resp
        client.head_object = AsyncMock(side_effect=err)

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.client = MagicMock(return_value=cm)

        storage = S3Storage(bucket="b", session=session)
        assert await storage.exists("test.txt") is False

    @pytest.mark.asyncio
    async def test_exists_raises_on_auth_or_network_error(self) -> None:
        client = AsyncMock()
        error_resp = {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}
        err = Exception("Access Denied")
        err.response = error_resp
        client.head_object = AsyncMock(side_effect=err)

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.client = MagicMock(return_value=cm)

        storage = S3Storage(bucket="b", session=session)
        with pytest.raises(Exception, match="Access Denied"):
            await storage.exists("test.txt")


class TestBatch4BAtomicReplaceDir:
    """F028: _atomic_replace_dir safely moves src to parent staging before swap."""

    def test_atomic_dir_replace(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "data.txt").write_text("restored data")

        dst = tmp_path / "target_dir" / "live"
        dst.parent.mkdir()
        dst.mkdir()
        (dst / "data.txt").write_text("old data")

        _atomic_replace_dir(str(src), str(dst))

        assert (dst / "data.txt").read_text() == "restored data"
        assert not src.exists()


class TestBatch4BIdempotencyKeyDefaults:
    """F029: Command classes create distinct IdempotencyKey instances by default."""

    def test_distinct_keys(self) -> None:
        cmd1 = CreateServerCommand(name="s1", minecraft_version="1.20.4")
        cmd2 = CreateServerCommand(name="s2", minecraft_version="1.20.4")
        assert cmd1.idempotency_key is not cmd2.idempotency_key
        assert str(cmd1.idempotency_key) != str(cmd2.idempotency_key)

        exp1 = SetServerExposureCommand(server_id="s1", method="playit", desired_state="running")
        exp2 = SetServerExposureCommand(server_id="s1", method="playit", desired_state="running")
        assert exp1.idempotency_key is not exp2.idempotency_key
        assert str(exp1.idempotency_key) != str(exp2.idempotency_key)

        bk1 = CreateBackupCommand(server_id="s1")
        bk2 = CreateBackupCommand(server_id="s1")
        assert bk1.idempotency_key is not bk2.idempotency_key
        assert str(bk1.idempotency_key) != str(bk2.idempotency_key)


class TestBatch4BBackupSaveAllOffset:
    """F070: BackupSaga._wait_for_save_confirmed only matches lines after baseline."""

    @pytest.mark.asyncio
    async def test_wait_for_save_confirmed_ignores_historical_lines(self) -> None:
        saga = BackupSaga(MagicMock())
        provider = AsyncMock()

        # History already has "Saved the game"
        baseline = ["Starting save", "Saved the game"]
        # In next call, only "Unrelated log" is returned (not yet saved again)
        # Then next call has new "Saved the game"
        call_count = 0

        async def mock_console(_handle, tail=200):  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ["Starting save", "Saved the game", "Log after baseline"]
            return ["Starting save", "Saved the game", "Log after baseline", "Saved the game"]

        provider.console = mock_console

        handle = MagicMock()
        await saga._wait_for_save_confirmed(
            BackupJobId(), ServerId("s1"), provider, handle, baseline_lines=baseline
        )
        assert call_count == 2


class TestBatch4BArqQueueRemoved:
    """F072: tasks/arq_queue.py must not exist."""

    def test_file_deleted(self) -> None:
        path = Path("backend/app/tasks/arq_queue.py")
        assert not path.exists()


class TestBatch4BQueueCancellation:
    """F073: InProcessQueue cancels background task and aborts cancelled tasks."""

    @pytest.mark.asyncio
    async def test_delayed_task_cancellation(self) -> None:
        from app.core.persistence.db import database

        async def session_factory():
            return database.session_factory()

        queue = InProcessQueue(session_factory)
        executed = False

        async def handler(_params):
            nonlocal executed
            executed = True

        queue.register("test_cancel_task", handler)
        task_id = await queue.enqueue("test_cancel_task", delay=2)

        status_before = await queue.get_status(task_id)
        assert status_before == TaskStatus.PENDING

        cancelled = await queue.cancel(task_id)
        assert cancelled is True

        status_after = await queue.get_status(task_id)
        assert status_after == TaskStatus.CANCELLED

        await asyncio.sleep(0.1)
        assert executed is False


class TestBatch4BCleanupTask:
    """F076: run_cleanup_task uses text SQL without table-string delete() errors."""

    @pytest.mark.asyncio
    async def test_cleanup_task_runs_successfully(self) -> None:
        result = await run_cleanup_task({
            "cleanup_logs": True,
            "cleanup_idempotency": True,
            "cleanup_events": True,
            "cleanup_task_queue": True,
        })
        assert "logs_deleted" in result
        assert "idempotency_keys_deleted" in result
        assert "events_deleted" in result
        assert "tasks_deleted" in result


class TestBatch4BTaskFallbacks:
    """F078: discovery_scan and health_check_task fall back gracefully when params omit objects."""

    @pytest.mark.asyncio
    async def test_discovery_scan_fallback(self) -> None:
        res = await periodic_discovery_scan({})
        assert "discovered" in res
        assert "already_known" in res

    @pytest.mark.asyncio
    async def test_health_check_task_fallback(self) -> None:
        res = await run_health_check_task({})
        assert "check_count" in res
        assert "results" in res


class TestBatch4BMetricsPrometheusWiring:
    """F079: MetricsCollector and PrometheusMetricsRegistry integration."""

    @pytest.mark.asyncio
    async def test_metrics_collection_updates_prometheus(self) -> None:
        from prometheus_client import CollectorRegistry

        from app.modules.monitoring.infrastructure.collector import MetricsCollector, ServerMetrics
        from app.modules.monitoring.infrastructure.metrics import PrometheusMetricsRegistry

        custom_registry = CollectorRegistry()
        prom = PrometheusMetricsRegistry(registry=custom_registry)
        collector = AsyncMock(spec=MetricsCollector)
        collector.collect_all = AsyncMock(
            return_value={
                "srv-1": ServerMetrics(
                    server_id="srv-1",
                    tps=19.8,
                    players=5,
                    ram_used_mb=512.0,
                    cpu_percent=12.5,
                )
            }
        )

        try:
            init_collector(collector, prometheus=prom)
            res = await run_metrics_collection_task({})

            assert res["server_count"] == 1
            assert res["results"]["srv-1"]["tps"] == 19.8
            assert (
                custom_registry.get_sample_value(
                    "mcs_server_tps", {"server_id": "srv-1"}
                )
                == 19.8
            )
            assert (
                custom_registry.get_sample_value(
                    "mcs_server_players", {"server_id": "srv-1"}
                )
                == 5.0
            )
        finally:
            init_collector(None, None)
