from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.event_bus import EventBus
from app.core.exceptions import ValidationError
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.activity.application.subscriber import ActivityEventSubscriber
from app.modules.backup.application.commands.create_backup import (
    CreateBackupCommand,
    CreateBackupHandler,
)
from app.modules.backup.application.queries.list_backups import (
    ListBackupsHandler,
    ListBackupsQuery,
)
from app.modules.backup.domain.aggregate import BackupTier
from app.modules.backup.domain.events import BackupCompletedEvent, BackupStartedEvent
from app.modules.versioning.application.baseline_adoption import BaselineAdoptionResult
from app.tasks.definitions.backup_task import run_backup_task


@pytest.fixture
async def isolated_db(tmp_path: Path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import app.modules.backup.infrastructure.models  # noqa: F401
    import app.modules.server.infrastructure.models  # noqa: F401

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p7_1_route.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine, old_factory = database._engine, database._session_factory
    database._engine = engine
    database._session_factory = factory
    yield factory
    database._engine, database._session_factory = old_engine, old_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_backup_and_list_backups_tier_routing(isolated_db) -> None:
    bus = EventBus()
    fake_queue = SimpleNamespace(enqueue=AsyncMock())

    with patch(
        "app.modules.backup.application.commands.create_backup.get_task_queue",
        return_value=fake_queue,
    ):
        handler = CreateBackupHandler(bus)
        r1 = await handler.handle(CreateBackupCommand(server_id="srv-1", tier="tier_1"))
        r2 = await handler.handle(
            CreateBackupCommand(
                server_id="srv-1",
                tier="tier_2",
                archive_format="tar.gz",
                include_cas_jars=True,
            )
        )
        assert r1.success and r2.success
        assert fake_queue.enqueue.await_count == 2
        payload2 = fake_queue.enqueue.await_args_list[1].args[1]
        assert payload2["tier"] == "tier_2"
        assert payload2["archive_format"] == "tar.gz"
        assert payload2["include_cas_jars"] is True

        with pytest.raises(ValidationError):
            await handler.handle(CreateBackupCommand(server_id="srv-1", tier="tier_3"))

    list_handler = ListBackupsHandler()
    t1_items = await list_handler.handle(ListBackupsQuery(server_id="srv-1", tier="tier_1"))
    t2_items = await list_handler.handle(ListBackupsQuery(server_id="srv-1", tier="tier_2"))
    assert len(t1_items) == 1 and t1_items[0].tier == "tier_1"
    assert len(t2_items) == 1 and t2_items[0].tier == "tier_2"


@pytest.mark.asyncio
async def test_run_backup_task_calls_baseline_hook_for_tier2_and_activity_labels(
    tmp_path: Path, isolated_db
) -> None:
    server_dir = tmp_path / "srv-1"
    (server_dir / "world").mkdir(parents=True)
    (server_dir / "world" / "level.dat").write_bytes(b"world")
    (server_dir / "server.properties").write_text("motd=Test\n", encoding="utf-8")

    # Seed server + backup job
    from app.modules.backup.domain.aggregate import BackupJob
    from app.modules.backup.infrastructure.repository import SQLBackupRepository
    from app.modules.server.infrastructure.models import ServerModel
    from app.modules.shared.value_objects import BackupJobId, ServerId

    async with isolated_db() as session:
        session.add(
            ServerModel(
                id="srv-1",
                name="Srv 1",
                server_type="vanilla",
                minecraft_version="1.21.1",
                port=25565,
                memory_min_mb=512,
                memory_max_mb=1024,
                root_path=str(server_dir),
                working_directory=".",
                provider="docker",
                location_type="docker",
                mode="simple",
            )
        )
        repo = SQLBackupRepository(session)
        await repo.save_job(BackupJob.create_tier2(BackupJobId("b-t2"), ServerId("srv-1")))
        await session.commit()

    fake_settings = SimpleNamespace(
        backup_local_dir=str(tmp_path / "backups"),
        backup_storage_path=str(tmp_path / "backup_storage"),
        backup_encryption_key_path=str(tmp_path / "backup.key"),
        storage_backend="local",
        host_state_dir=str(tmp_path / "host_state"),
        host_state_host_dir="",
        host_data_dir="",
        servers_data_dir=str(tmp_path / "servers"),
    )

    with (
        patch("app.tasks.definitions.backup_task.ConfigFactory.global_settings", return_value=fake_settings),
        patch(
            "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
            AsyncMock(return_value=BaselineAdoptionResult(status="created", files_count=1, cas_ingested=0)),
        ) as mock_adopt,
    ):
        res = await run_backup_task(
            {
                "backup_id": "b-t2",
                "server_id": "srv-1",
                "tier": BackupTier.TIER_2.value,
                "archive_format": "tar.gz",
                "encrypt": False,
            }
        )
        mock_adopt.assert_awaited_once_with("srv-1")
        assert res["backup_id"] == "b-t2"

    sub = ActivityEventSubscriber(AsyncMock())
    msg1, act1 = sub._resolve_summary_and_type(
        BackupStartedEvent(backup_id="12345678", server_id="srv-1", tier="tier_1"),
        "BackupStartedEvent",
    )
    msg2, act2 = sub._resolve_summary_and_type(
        BackupCompletedEvent(
            backup_id="12345678", server_id="srv-1", size_bytes=10, checksum="aa", tier="tier_2"
        ),
        "BackupCompletedEvent",
    )
    assert act1 == "backup.started" and "Tier-1" in msg1
    assert act2 == "backup.completed" and "Tier-2" in msg2


@pytest.mark.asyncio
async def test_run_backup_task_tier1_uses_backup_storage_path_and_publishes_events(
    tmp_path: Path, isolated_db
) -> None:
    server_dir = tmp_path / "srv-t1"
    (server_dir / "world").mkdir(parents=True)
    (server_dir / "world" / "level.dat").write_bytes(b"world")
    (server_dir / "server.properties").write_text("motd=Test\n", encoding="utf-8")

    from app.core.exceptions import NotFoundError
    from app.modules.backup.domain.aggregate import BackupJob
    from app.modules.backup.domain.events import BackupFailedEvent
    from app.modules.backup.infrastructure.repository import SQLBackupRepository
    from app.modules.server.infrastructure.models import ServerModel
    from app.modules.shared.value_objects import BackupJobId, ServerId

    async with isolated_db() as session:
        session.add(
            ServerModel(
                id="srv-t1",
                name="Srv T1",
                server_type="vanilla",
                minecraft_version="1.21.1",
                port=25565,
                memory_min_mb=512,
                memory_max_mb=1024,
                root_path=str(server_dir),
                working_directory=".",
                provider="docker",
                location_type="docker",
                mode="simple",
            )
        )
        repo = SQLBackupRepository(session)
        await repo.save_job(BackupJob.create_tier1(BackupJobId("b-t1-ok"), ServerId("srv-t1")))
        await repo.save_job(
            BackupJob.create_tier1(BackupJobId("b-t1-fail"), ServerId("srv-missing"))
        )
        await session.commit()

    # Intentionally omit backup_local_dir to verify backup_storage_path is used
    fake_settings = SimpleNamespace(
        backup_storage_path=str(tmp_path / "backup_storage"),
        backup_encryption_key_path=str(tmp_path / "backup.key"),
        storage_backend="local",
        host_state_dir=str(tmp_path / "host_state"),
        host_state_host_dir="",
        host_data_dir="",
        servers_data_dir=str(tmp_path / "servers"),
    )

    from app.core.event_bus import DomainEvent, EventHandler

    bus = EventBus()
    published: list[DomainEvent] = []

    class _CaptureHandler(EventHandler):
        async def handle(self, event: DomainEvent) -> None:
            published.append(event)

    handler = _CaptureHandler()
    bus.subscribe("BackupCompletedEvent", handler)
    bus.subscribe("BackupFailedEvent", handler)

    with (
        patch(
            "app.tasks.definitions.backup_task.ConfigFactory.global_settings",
            return_value=fake_settings,
        ),
        patch(
            "app.tasks.definitions.backup_task.get_optional_event_bus",
            return_value=bus,
        ),
        patch(
            "app.tasks.definitions.backup_task.ensure_simple_baseline_lockfile",
            AsyncMock(
                return_value=BaselineAdoptionResult(status="created", files_count=1, cas_ingested=0)
            ),
        ),
    ):
        res = await run_backup_task(
            {
                "backup_id": "b-t1-ok",
                "server_id": "srv-t1",
                "tier": BackupTier.TIER_1.value,
                "two_tier": True,
            }
        )
        assert res == {"backup_id": "b-t1-ok", "server_id": "srv-t1"}
        assert any(isinstance(e, BackupCompletedEvent) for e in published)
        assert (tmp_path / "backup_storage" / "tier1" / "srv-t1" / "b-t1-ok").is_dir()

        with pytest.raises(NotFoundError):
            await run_backup_task(
                {
                    "backup_id": "b-t1-fail",
                    "server_id": "srv-missing",
                    "tier": BackupTier.TIER_1.value,
                    "two_tier": True,
                }
            )
        assert any(isinstance(e, BackupFailedEvent) for e in published)
