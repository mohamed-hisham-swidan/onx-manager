from __future__ import annotations

from typing import Any

import pytest

from app.core.event_bus import DomainEvent, EventBus, EventHandler
from app.core.persistence.db import database
from app.modules.server.application.commands.update_server_config import (
    UpdateServerConfigCommand,
    UpdateServerConfigHandler,
)
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.events import ServerConfigChangedEvent
from app.modules.server.domain.value_objects import (
    CpuAllocation,
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId


class EventCollector(EventHandler):
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def handle(self, event: DomainEvent) -> None:
        self.events.append(event)


async def _get_server(server_id: str) -> Server:
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        return await repo.get(ServerId(server_id))


async def _create_test_server(
    server_id: str,
    tmp_path: Any,
    cpu: CpuAllocation | None = None,
    java_args: JavaArguments | None = None,
) -> Server:
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path=str(tmp_path),
            working_directory=".",
            startup_jar="server.jar",
        )
        server = Server.create(
            server_id=ServerId(server_id),
            name="TestServer",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=java_args or JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
            deployment=deployment,
            cpu=cpu or CpuAllocation(),
        )
        await repo.save(server)
        await session.commit()
        return server


@pytest.mark.usefixtures("init_test_db")
class TestUpdateServerConfigCpuAndJvm:
    @pytest.mark.asyncio
    async def test_update_cpu_cores_and_affinity(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        server_id = "test-cpu-update"
        await _create_test_server(server_id, tmp_path)

        collector = EventCollector()
        event_bus.subscribe("ServerConfigChangedEvent", collector)

        handler = UpdateServerConfigHandler(event_bus)
        result = await handler.handle(
            UpdateServerConfigCommand(
                server_id=server_id,
                cpu_cores=4,
                cpu_affinity="0-3",
            )
        )

        assert result.success is True
        loaded = await _get_server(server_id)
        assert loaded.cpu.cores == 4
        assert loaded.cpu.affinity == "0-3"

        config_events = [e for e in collector.events if isinstance(e, ServerConfigChangedEvent)]
        assert len(config_events) == 1
        assert "cpu" in config_events[0].changed_keys

    @pytest.mark.asyncio
    async def test_update_cpu_preserves_existing_affinity_when_only_cores_given(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        server_id = "test-cpu-preserve-aff"
        await _create_test_server(
            server_id, tmp_path, cpu=CpuAllocation(cores=2, affinity="0,1")
        )

        handler = UpdateServerConfigHandler(event_bus)
        result = await handler.handle(
            UpdateServerConfigCommand(
                server_id=server_id,
                cpu_cores=6,
            )
        )

        assert result.success is True
        loaded = await _get_server(server_id)
        assert loaded.cpu.cores == 6
        assert loaded.cpu.affinity == "0,1"

    @pytest.mark.asyncio
    async def test_update_cpu_preserves_existing_cores_when_only_affinity_given(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        server_id = "test-cpu-preserve-cores"
        await _create_test_server(
            server_id, tmp_path, cpu=CpuAllocation(cores=4, affinity="0-1")
        )

        handler = UpdateServerConfigHandler(event_bus)
        result = await handler.handle(
            UpdateServerConfigCommand(
                server_id=server_id,
                cpu_affinity="2-3",
            )
        )

        assert result.success is True
        loaded = await _get_server(server_id)
        assert loaded.cpu.cores == 4
        assert loaded.cpu.affinity == "2-3"

    @pytest.mark.asyncio
    async def test_update_java_args(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        server_id = "test-jvm-args-update"
        await _create_test_server(server_id, tmp_path)

        collector = EventCollector()
        event_bus.subscribe("ServerConfigChangedEvent", collector)

        handler = UpdateServerConfigHandler(event_bus)
        result = await handler.handle(
            UpdateServerConfigCommand(
                server_id=server_id,
                java_args=["-XX:+UseG1GC", "-Dlog4j2.formatMsgNoLookups=true"],
            )
        )

        assert result.success is True
        loaded = await _get_server(server_id)
        assert loaded.java_args.as_list() == [
            "-XX:+UseG1GC",
            "-Dlog4j2.formatMsgNoLookups=true",
        ]

        config_events = [e for e in collector.events if isinstance(e, ServerConfigChangedEvent)]
        assert len(config_events) == 1
        assert "java_args" in config_events[0].changed_keys

    @pytest.mark.asyncio
    async def test_properties_patch_preserves_unknown_keys_on_disk(
        self, event_bus: EventBus, tmp_path
    ) -> None:
        server_id = "test-props-unknown"
        await _create_test_server(server_id, tmp_path)

        props_file = tmp_path / "server.properties"
        props_file.write_text(
            "# Server properties\n"
            "server-name=TestServer\n"
            "motd=Old MOTD\n"
            "custom-plugin-key=custom_value_123\n"
            "another.custom.prop=true\n",
            encoding="utf-8",
        )

        handler = UpdateServerConfigHandler(event_bus)
        result = await handler.handle(
            UpdateServerConfigCommand(
                server_id=server_id,
                properties={
                    "motd": "Updated MOTD",
                    "custom-plugin-key": "updated_custom_value",
                    "brand-new-unknown": "fresh_setting",
                },
            )
        )

        assert result.success is True
        content = props_file.read_text(encoding="utf-8")
        assert "motd=Updated MOTD" in content
        assert "custom-plugin-key=updated_custom_value" in content
        assert "brand-new-unknown=fresh_setting" in content
        assert "another.custom.prop=true" in content
