from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.event_bus import DomainEvent
from app.modules.activity.application.subscriber import ActivityEventSubscriber
from app.modules.activity.domain.entities import ServerActivityLog
from app.modules.backup.domain.events import (
    BackupCompletedEvent,
    BackupRestoredEvent,
)
from app.modules.plugin.domain.events import (
    PluginDisabledEvent,
    PluginInstalledEvent,
)
from app.modules.server.domain.events import (
    ServerConfigChangedEvent,
    ServerCrashedEvent,
    ServerCreatedEvent,
    ServerStartedEvent,
    ServerStoppedEvent,
)
from app.modules.shared.value_objects import ServerId
from app.modules.versioning.domain.events import (
    BranchCreatedEvent,
    CommitCreatedEvent,
    CommitPromotedEvent,
    TestRunCompletedEvent,
    TestRunStartedEvent,
)


class InMemoryActivityRepository:
    def __init__(self) -> None:
        self.logs: list[ServerActivityLog] = []

    async def save(self, log: ServerActivityLog) -> None:
        self.logs.append(log)

    async def list_by_server(self, *_args: object, **_kwargs: object):
        return self.logs, len(self.logs)

    async def delete_older_than(self, *_args: object, **_kwargs: object):
        return 0


@pytest.mark.asyncio
async def test_subscriber_records_lifecycle_events():
    repo = InMemoryActivityRepository()
    subscriber = ActivityEventSubscriber(repo)
    sid = ServerId("srv-life-1")

    # Created
    await subscriber.handle(
        ServerCreatedEvent(
            server_id=sid,
            name="My Test Server",
            minecraft_version="1.21.1",
        )
    )
    # Started
    await subscriber.handle(ServerStartedEvent(server_id=sid, pid=1234, port=25565))
    # Config changed
    await subscriber.handle(ServerConfigChangedEvent(server_id=sid, changed_keys=["motd", "pvp"]))
    # Crashed
    await subscriber.handle(
        ServerCrashedEvent(server_id=sid, exit_code=1, last_log_lines=["Crash!"])
    )
    # Stopped
    await subscriber.handle(ServerStoppedEvent(server_id=sid))

    assert len(repo.logs) == 5
    assert repo.logs[0].event_type == "server.created"
    assert "Server 'My Test Server' created (1.21.1)" in repo.logs[0].summary
    assert repo.logs[1].event_type == "server.started"
    assert repo.logs[2].event_type == "server.config_changed"
    assert repo.logs[3].event_type == "server.crashed"
    assert "exit code: 1" in repo.logs[3].summary
    assert repo.logs[4].event_type == "server.stopped"


@pytest.mark.asyncio
async def test_subscriber_records_plugin_and_backup_events():
    repo = InMemoryActivityRepository()
    subscriber = ActivityEventSubscriber(repo)

    # Plugin installed
    await subscriber.handle(
        PluginInstalledEvent(
            plugin_id="essentialsx",
            server_id="srv-plug-1",
            version="2.20.1",
            name="EssentialsX",
        )
    )
    # Plugin disabled
    await subscriber.handle(
        PluginDisabledEvent(
            plugin_id="essentialsx",
            server_id="srv-plug-1",
        )
    )
    # Backup completed
    await subscriber.handle(
        BackupCompletedEvent(
            backup_id="bk-123456789",
            server_id="srv-plug-1",
            size_bytes=1048576,
            checksum="abc123sha",
        )
    )
    # Backup restored
    await subscriber.handle(
        BackupRestoredEvent(
            backup_id="bk-123456789",
            server_id="srv-plug-1",
        )
    )

    assert len(repo.logs) == 4
    assert repo.logs[0].event_type == "plugin.installed"
    assert "EssentialsX" in repo.logs[0].summary
    assert repo.logs[1].event_type == "plugin.disabled"
    assert "essentialsx" in repo.logs[1].summary
    assert repo.logs[2].event_type == "backup.completed"
    assert repo.logs[3].event_type == "backup.restored"


@pytest.mark.asyncio
async def test_subscriber_records_versioning_events():
    repo = InMemoryActivityRepository()
    subscriber = ActivityEventSubscriber(repo)

    # Branch created
    await subscriber.handle(
        BranchCreatedEvent(
            server_id="srv-v1",
            branch_name="feature-mod-update",
            branch_id="br-1",
        )
    )
    # Commit created
    await subscriber.handle(
        CommitCreatedEvent(
            server_id="srv-v1",
            commit_id="cm-abcdef123",
            message="Add Dynmap and update Fabric loader",
            branch_name="feature-mod-update",
        )
    )
    # Test run started
    await subscriber.handle(
        TestRunStartedEvent(
            server_id="srv-v1",
            test_id="test-run-1",
            commit_id="cm-abcdef123",
            bot_count=5,
            duration_minutes=10,
        )
    )
    # Test run completed
    await subscriber.handle(
        TestRunCompletedEvent(
            server_id="srv-v1",
            test_id="test-run-1",
            commit_id="cm-abcdef123",
            passed=True,
        )
    )
    # Commit promoted
    await subscriber.handle(
        CommitPromotedEvent(
            server_id="srv-v1",
            commit_id="cm-abcdef123",
            test_id="test-run-1",
            keep_world_changes=False,
        )
    )

    assert len(repo.logs) == 5
    assert repo.logs[0].event_type == "versioning.branch_created"
    assert "feature-mod-update" in repo.logs[0].summary
    assert repo.logs[1].event_type == "versioning.commit_created"
    assert "Add Dynmap" in repo.logs[1].summary
    assert repo.logs[2].event_type == "versioning.test_started"
    assert "5 bots" in repo.logs[2].summary
    assert repo.logs[3].event_type == "versioning.test_completed"
    assert "verification passed" in repo.logs[3].summary
    assert repo.logs[4].event_type == "versioning.promoted"


@pytest.mark.asyncio
async def test_commit_promoted_event_historical_json_deserializes_and_is_handled():
    """P3-1: historical CommitPromotedEvent payloads must remain readable."""
    historical_json = (
        '{"event_id": "e-hist-1", "event_type": "CommitPromotedEvent", '
        '"timestamp": 1700000000.0, "correlation_id": "", "schema_version": 1, '
        '"server_id": "srv-v1", "commit_id": "cm-abcdef123", '
        '"test_id": "test-run-1", "keep_world_changes": false, '
        '"forced": true, "actor_id": "admin-1"}'
    )
    event = CommitPromotedEvent.model_validate_json(historical_json)
    assert event.server_id == "srv-v1"
    assert event.commit_id == "cm-abcdef123"
    assert event.test_id == "test-run-1"
    assert event.forced is True
    assert event.actor_id == "admin-1"

    repo = InMemoryActivityRepository()
    subscriber = ActivityEventSubscriber(repo)
    await subscriber.handle(event)

    assert len(repo.logs) == 1
    assert repo.logs[0].event_type == "versioning.promoted"
    assert repo.logs[0].server_id == "srv-v1"
    assert "cm-abcde" in repo.logs[0].summary


@pytest.mark.asyncio
async def test_subscriber_resilience_on_repo_failure():
    mock_repo = AsyncMock()
    mock_repo.save.side_effect = RuntimeError("DB connection dropped")

    subscriber = ActivityEventSubscriber(mock_repo)
    event = ServerStoppedEvent(server_id=ServerId("srv-resilient"))

    # Must catch exception and NOT raise
    await subscriber.handle(event)
    mock_repo.save.assert_called_once()


@pytest.mark.asyncio
async def test_subscriber_ignores_events_without_server_id():
    class GlobalEvent(DomainEvent):
        name: str

    repo = InMemoryActivityRepository()
    subscriber = ActivityEventSubscriber(repo)

    await subscriber.handle(GlobalEvent(name="global_settings_changed"))
    assert len(repo.logs) == 0


@pytest.mark.asyncio
async def test_subscriber_prefers_plugin_name_and_filename_over_hex_id():
    from app.modules.plugin.domain.events import PluginEnabledEvent

    repo = InMemoryActivityRepository()
    subscriber = ActivityEventSubscriber(repo)

    await subscriber.handle(
        PluginEnabledEvent(
            plugin_id="03b2ea67c4db450faac98f39f021b318",
            server_id="srv-plug-1",
            name="SkinsRestorer 15.12.6",
            filename="SkinsRestorer.jar",
        )
    )
    await subscriber.handle(
        PluginDisabledEvent(
            plugin_id="47dde75b8c0b4008a5e100762fb66824",
            server_id="srv-plug-1",
            name="6.2.1",
            filename="TAB v6.2.1.jar",
        )
    )

    assert repo.logs[0].summary == "Plugin/mod 'SkinsRestorer 15.12.6' enabled"
    assert repo.logs[1].summary == "Plugin/mod 'TAB v6.2.1' disabled"
