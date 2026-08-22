from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.exceptions import InvalidValueError
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.events import (
    ServerConfigChangedEvent,
    ServerCreatedEvent,
    ServerCrashedEvent,
    ServerStartedEvent,
    ServerStartingEvent,
    ServerStoppedEvent,
    ServerStoppingEvent,
)
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
    ServerType,
)
from app.modules.shared.value_objects import MinecraftVersion, ServerId


@pytest.fixture
def valid_server() -> Server:
    props = ServerProperties(port=PortNumber(25565))
    return Server.create(
        server_id=ServerId("test-1"),
        name="Test Server",
        server_type=ServerType.VANILLA,
        minecraft_version=MinecraftVersion.parse("1.21.4"),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(["-Xmx2G"]),
        properties=props,
    )


class TestServerCreation:
    def test_create_emits_event(self, valid_server: Server) -> None:
        events = valid_server.collect_events()
        assert len(events) == 1
        assert isinstance(events[0], ServerCreatedEvent)
        assert events[0].name == "Test Server"

    def test_initial_status(self, valid_server: Server) -> None:
        assert valid_server.status == ServerStatus.CREATED

    def test_properties(self, valid_server: Server) -> None:
        assert valid_server.id == ServerId("test-1")
        assert valid_server.name == "Test Server"
        assert valid_server.minecraft_version == MinecraftVersion(1, 21, 4)


class TestServerStateMachine:
    def test_start_transition(self, valid_server: Server) -> None:
        valid_server.start()
        assert valid_server.status == ServerStatus.STARTING
        events = valid_server.collect_events()
        assert any(isinstance(e, ServerStartingEvent) for e in events)

    def test_start_to_running(self, valid_server: Server) -> None:
        valid_server.start()
        valid_server.mark_running(pid=12345, port=25565)
        assert valid_server.status == ServerStatus.RUNNING
        assert valid_server.runtime is not None
        assert valid_server.runtime.pid == 12345
        events = valid_server.collect_events()
        assert any(isinstance(e, ServerStartedEvent) for e in events)

    def test_running_to_stopping(self, valid_server: Server) -> None:
        valid_server.start()
        valid_server.mark_running(pid=12345, port=25565)
        valid_server.stop(reason="maintenance")
        assert valid_server.status == ServerStatus.STOPPING
        events = valid_server.collect_events()
        assert any(isinstance(e, ServerStoppingEvent) for e in events)

    def test_stopping_to_stopped(self, valid_server: Server) -> None:
        valid_server.start()
        valid_server.mark_running(pid=12345, port=25565)
        valid_server.stop()
        valid_server.mark_stopped()
        assert valid_server.status == ServerStatus.STOPPED
        assert valid_server.deployment is None
        events = valid_server.collect_events()
        assert any(isinstance(e, ServerStoppedEvent) for e in events)

    def test_running_to_crashed(self, valid_server: Server) -> None:
        valid_server.start()
        valid_server.mark_running(pid=12345, port=25565)
        valid_server.crash(exit_code=1, last_log_lines=["OutOfMemoryError"])
        assert valid_server.status == ServerStatus.CRASHED
        assert valid_server.deployment is None
        events = valid_server.collect_events()
        assert any(isinstance(e, ServerCrashedEvent) for e in events)
        crashed = [e for e in events if isinstance(e, ServerCrashedEvent)][0]
        assert crashed.exit_code == 1
        assert "OutOfMemoryError" in crashed.last_log_lines

    def test_restart_after_crash(self, valid_server: Server) -> None:
        valid_server.start()
        valid_server.mark_running(pid=1, port=25565)
        valid_server.crash(exit_code=1)
        valid_server.start()
        assert valid_server.status == ServerStatus.STARTING

    def test_invalid_transition_raises(self, valid_server: Server) -> None:
        with pytest.raises(InvalidValueError):
            valid_server.mark_running(pid=1, port=25565)

    def test_invalid_transition_from_stopped(self, valid_server: Server) -> None:
        valid_server.start()
        valid_server.mark_running(pid=1, port=25565)
        valid_server.stop()
        valid_server.mark_stopped()
        with pytest.raises(InvalidValueError):
            valid_server.stop()


class TestServerProvisioningFlow:
    def test_begin_provisioning(self, valid_server: Server) -> None:
        valid_server.begin_provisioning()
        assert valid_server.status == ServerStatus.PROVISIONING

    def test_finish_provisioning_returns_to_created(self, valid_server: Server) -> None:
        valid_server.begin_provisioning()
        valid_server.finish_provisioning()
        assert valid_server.status == ServerStatus.CREATED

    def test_fail_provisioning_marks_provisioning_failed(self, valid_server: Server) -> None:
        valid_server.begin_provisioning()
        valid_server.fail_provisioning(error="download error", retryable=True)
        assert valid_server.status == ServerStatus.PROVISIONING_FAILED
        assert valid_server.provisioning_error == "download error"
        assert valid_server.provisioning_retryable is True

    def test_fail_provisioning_fatal_marks_broken(self, valid_server: Server) -> None:
        valid_server.begin_provisioning()
        valid_server.fail_provisioning(error="out of disk", fatal=True)
        assert valid_server.status == ServerStatus.BROKEN
        assert valid_server.provisioning_error == "out of disk"
        assert valid_server.provisioning_retryable is False

    def test_provisioning_can_start(self, valid_server: Server) -> None:
        valid_server.begin_provisioning()
        valid_server.start()
        assert valid_server.status == ServerStatus.STARTING

    def test_cannot_provision_from_starting(self, valid_server: Server) -> None:
        valid_server.start()
        with pytest.raises(InvalidValueError):
            valid_server.begin_provisioning()

    def test_cannot_finish_provisioning_from_created(self, valid_server: Server) -> None:
        with pytest.raises(InvalidValueError):
            valid_server.finish_provisioning()


class TestServerConfig:
    def test_update_properties(self, valid_server: Server) -> None:
        valid_server.start()
        valid_server.mark_running(pid=1, port=25565)
        valid_server.update_properties(motd="New MOTD", max_players=50)
        assert valid_server.properties.motd == "New MOTD"
        assert valid_server.properties.max_players == 50
        events = valid_server.collect_events()
        assert any(isinstance(e, ServerConfigChangedEvent) for e in events)

    def test_update_memory(self, valid_server: Server) -> None:
        new_memory = MemoryAllocation(2048, 4096)
        valid_server.update_memory(new_memory)
        assert valid_server.memory == new_memory

    def test_mark_deleted_emits_event(self, valid_server: Server) -> None:
        valid_server.mark_deleted()
        from app.modules.server.domain.events import ServerDeletedEvent

        events = valid_server.collect_events()
        assert any(isinstance(e, ServerDeletedEvent) for e in events)


class TestServerEdgeCases:
    def test_custom_created_at(self) -> None:
        past = datetime(2024, 1, 1, tzinfo=timezone.utc)
        props = ServerProperties(port=PortNumber(25565))
        server = Server(
            server_id=ServerId("old"),
            name="Old Server",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion(1, 20),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=props,
            created_at=past,
        )
        assert server.created_at == past

    def test_group_id_default(self, valid_server: Server) -> None:
        assert valid_server.group_id == "default"


class TestServerRename:
    def test_rename_updates_name_and_emits_event(self, valid_server: Server) -> None:
        valid_server.collect_events()
        valid_server.rename("New Awesome Server")
        assert valid_server.name == "New Awesome Server"
        events = valid_server.collect_events()
        assert len(events) == 1
        assert isinstance(events[0], ServerConfigChangedEvent)
        assert "name" in events[0].changed_keys

    def test_rename_same_name_is_noop(self, valid_server: Server) -> None:
        valid_server.collect_events()
        valid_server.rename("Test Server")
        assert valid_server.name == "Test Server"
        events = valid_server.collect_events()
        assert len(events) == 0

    def test_rename_empty_name_raises_invalid_value_error(self, valid_server: Server) -> None:
        with pytest.raises(InvalidValueError):
            valid_server.rename("")
        with pytest.raises(InvalidValueError):
            valid_server.rename("   ")

