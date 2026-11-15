import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.core.command_bus import (
    Command,
    CommandBus,
    CommandHandler,
    CommandResult,
    DatabaseBusyRetryMiddleware,
)
from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.activity.application.subscriber import ActivityEventSubscriber
from app.modules.activity.infrastructure.repository import SQLActivityRepository
from app.modules.monitoring.infrastructure.collector import MetricsCollector
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.commands.create_branch import (
    CreateBranchCommand,
    CreateBranchHandler,
)
from app.modules.versioning.application.commands.create_commit import (
    CreateCommitCommand,
    CreateCommitHandler,
)
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository


class DummyCommand(Command):
    name: str


class FlakyLockingHandler(CommandHandler[DummyCommand]):
    def __init__(self, fail_count: int = 2) -> None:
        self.attempts = 0
        self.fail_count = fail_count

    async def handle(self, command: DummyCommand) -> CommandResult:
        _ = command
        self.attempts += 1
        if self.attempts <= self.fail_count:
            raise OperationalError("INSERT INTO foo", {}, Exception("database is locked"))
        return CommandResult(success=True, data={"attempts": self.attempts})


@pytest.mark.asyncio
async def test_command_bus_busy_retry_middleware_recovers() -> None:
    bus = CommandBus()
    bus.add_middleware(DatabaseBusyRetryMiddleware(max_retries=3, initial_delay=0.01))
    handler = FlakyLockingHandler(fail_count=2)
    bus.register(DummyCommand, handler)

    result = await bus.send(DummyCommand(name="test"))
    assert result.success is True
    assert result.data == {"attempts": 3}
    assert handler.attempts == 3


@pytest.mark.asyncio
async def test_command_bus_busy_retry_exhaustion_bubbles_error() -> None:
    bus = CommandBus()
    bus.add_middleware(DatabaseBusyRetryMiddleware(max_retries=2, initial_delay=0.01))
    handler = FlakyLockingHandler(fail_count=3)
    bus.register(DummyCommand, handler)

    result = await bus.send(DummyCommand(name="test"))
    assert result.success is False
    assert result.error_code == "UNEXPECTED_ERROR"
    assert "database is locked" in (result.error or "")
    assert handler.attempts == 2


@pytest.mark.asyncio
async def test_create_branch_post_commit_with_activity_subscriber() -> None:
    server_id = f"test-srv-{uuid.uuid4().hex[:8]}"

    # Seed test server
    async with database.session_factory() as sess:
        server = ServerModel(
            id=server_id,
            name="LockTestServer",
            server_type="paper",
            minecraft_version="1.21.4",
            status="STOPPED",
            root_path=f"/tmp/servers/{server_id}",
            port=25565,
            mode="advanced",
        )
        sess.add(server)
        await sess.commit()

    event_bus = EventBus()
    activity_repo = SQLActivityRepository()
    subscriber = ActivityEventSubscriber(activity_repo)
    event_bus.subscribe("BranchCreatedEvent", subscriber)

    handler = CreateBranchHandler(event_bus=event_bus)
    branch_name = f"feat-{uuid.uuid4().hex[:6]}"

    # Must execute within 3.0 seconds without timing out on event subscriber
    res = await asyncio.wait_for(
        handler.handle(CreateBranchCommand(server_id=server_id, name=branch_name)),
        timeout=3.0,
    )
    assert res.success is True
    assert res.entity_id is not None

    # Verify branch was saved
    async with database.session_factory() as sess:
        v_repo = SQLVersioningRepository(sess)
        branch = await v_repo.get_branch(res.entity_id)
        assert branch is not None
        assert branch.name == branch_name

    # Verify activity was saved
    activities, count = await activity_repo.list_by_server(server_id, limit=10)
    assert count >= 1
    assert any(a.event_type == "versioning.branch_created" for a in activities)


@pytest.mark.asyncio
async def test_create_commit_post_commit_with_activity_subscriber(tmp_path) -> None:
    server_id = f"test-srv-{uuid.uuid4().hex[:8]}"
    server_dir = tmp_path / server_id
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "server.properties").write_text("motd=test\n")

    # Seed test server
    async with database.session_factory() as sess:
        server = ServerModel(
            id=server_id,
            name="CommitLockServer",
            server_type="paper",
            minecraft_version="1.21.4",
            status="STOPPED",
            root_path=str(server_dir),
            port=25565,
            mode="advanced",
        )
        sess.add(server)
        await sess.commit()

    event_bus = EventBus()
    activity_repo = SQLActivityRepository()
    subscriber = ActivityEventSubscriber(activity_repo)
    event_bus.subscribe("CommitCreatedEvent", subscriber)

    handler = CreateCommitHandler(event_bus=event_bus)

    with (
        patch(
            "app.modules.versioning.infrastructure.storage_probe.StorageCapabilityProbe.assert_supports_reflink"
        ),
        patch(
            "app.modules.versioning.infrastructure.btrfs_zfs_driver.BtrfsZfsSnapshotDriver.create_snapshot",
            return_value=1024,
        ),
    ):
        res = await asyncio.wait_for(
            handler.handle(
                CreateCommitCommand(
                    server_id=server_id,
                    message="Initial lock test commit",
                    branch_name="main",
                )
            ),
            timeout=3.0,
        )

    assert res.success is True
    commit_id = res.entity_id
    assert commit_id is not None

    activities, count = await activity_repo.list_by_server(server_id, limit=10)
    assert count >= 1
    assert any(a.event_type == "versioning.commit_created" for a in activities)


@pytest.mark.asyncio
async def test_collector_psutil_and_rcon_outside_session() -> None:
    collector = MetricsCollector()
    server_id = f"test-srv-{uuid.uuid4().hex[:8]}"

    # Seed server
    async with database.session_factory() as sess:
        server = ServerModel(
            id=server_id,
            name="MetricsTestServer",
            server_type="paper",
            minecraft_version="1.21.4",
            status="RUNNING",
            root_path=f"/tmp/servers/{server_id}",
            deployment_pid=999999,
            port=25565,
        )
        sess.add(server)
        await sess.commit()

    called = []

    def fake_collect_process(pid, _cache):
        called.append(pid)
        return (512.0, 15.0)

    with (
        patch(
            "app.modules.monitoring.infrastructure.collector._collect_process_metrics",
            side_effect=fake_collect_process,
        ),
        patch(
            "app.modules.monitoring.infrastructure.repository.SQLMetricRepository.record",
            new_callable=AsyncMock,
        ),
    ):
        metric = await collector.collect(server_id)
        assert metric.ram_used_mb == 512.0
        assert metric.cpu_percent == 15.0
        assert called == [999999]
