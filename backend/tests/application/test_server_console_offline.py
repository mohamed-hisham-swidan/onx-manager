from __future__ import annotations

from pathlib import Path

import pytest

from app.core.persistence.db import database
from app.modules.server.application.queries.get_server_console import (
    GetServerConsoleHandler,
    GetServerConsoleQuery,
    read_log_tail_from_disk,
)
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
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

pytestmark = pytest.mark.usefixtures("init_test_db")


class TestServerConsoleOfflineFallback:
    def test_read_log_tail_from_disk_missing_file(self, tmp_path: Path) -> None:
        missing_log = tmp_path / "logs" / "latest.log"
        lines = read_log_tail_from_disk(missing_log, tail=50)
        assert lines == ["No log file exists on disk yet"]

    def test_read_log_tail_from_disk_empty_file(self, tmp_path: Path) -> None:
        empty_log = tmp_path / "latest.log"
        empty_log.write_text("", encoding="utf-8")
        lines = read_log_tail_from_disk(empty_log, tail=50)
        assert lines == ["No log file exists on disk yet"]

    def test_read_log_tail_from_disk_normal_file(self, tmp_path: Path) -> None:
        log_file = tmp_path / "latest.log"
        content = "\n".join([f"[INFO] Log line {i}" for i in range(1, 101)])
        log_file.write_text(content, encoding="utf-8")

        lines = read_log_tail_from_disk(log_file, tail=10)
        assert len(lines) == 10
        assert lines[-1] == "[INFO] Log line 100"
        assert lines[0] == "[INFO] Log line 91"

    def test_read_log_tail_from_disk_large_file_seek(self, tmp_path: Path) -> None:
        log_file = tmp_path / "large.log"
        # Generate >300KB file
        repeated_line = "[INFO] Minecraft server tick monitor heartbeat event log entry\n"
        with open(log_file, "wb") as f:
            for i in range(5000):
                f.write(f"[{i:05d}] {repeated_line}".encode())
            f.write(b"[09999] [INFO] Final line of the massive log file\n")

        assert log_file.stat().st_size > 300 * 1024

        # Using small buffer size to test seek behavior
        lines = read_log_tail_from_disk(log_file, tail=5, buffer_size=4096)
        assert len(lines) == 5
        assert lines[-1] == "[09999] [INFO] Final line of the massive log file"

    @pytest.mark.asyncio
    async def test_handler_reads_disk_when_stopped(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "srv_stopped"
        logs_dir = server_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        latest_log = logs_dir / "latest.log"
        latest_log.write_text(
            "[12:00:00] [INFO] Starting minecraft server version 1.20.1\n"
            "[12:00:05] [WARN] Can't keep up! Is the server overloaded?\n"
            "[12:00:10] [INFO] Stopping server\n"
            "[12:00:11] [INFO] Saving worlds\n",
            encoding="utf-8",
        )

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = Server.create(
                server_id=ServerId("srv-offline-1"),
                name="StoppedServer",
                server_type=ServerType.PAPER,
                minecraft_version=MinecraftVersion.parse("1.20.4"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments([]),
                properties=ServerProperties(PortNumber(25565)),
                deployment=ServerDeployment(
                    location_type=LocationType.LOCAL,
                    root_path=str(server_dir),
                    working_directory=".",
                    startup_jar="server.jar",
                ),
            )
            server_id = str(server.id)
            await repo.save(server)
            await session.commit()

        handler = GetServerConsoleHandler()
        result = await handler.handle(GetServerConsoleQuery(server_id=server_id, tail=10))
        assert len(result.lines) == 4
        assert "[12:00:00] [INFO] Starting minecraft server version 1.20.1" in result.lines[0]
        assert "[12:00:11] [INFO] Saving worlds" in result.lines[-1]

    @pytest.mark.asyncio
    async def test_handler_clean_empty_state_when_no_log_file(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "srv_no_log"
        server_dir.mkdir(parents=True, exist_ok=True)

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = Server.create(
                server_id=ServerId("srv-offline-2"),
                name="NoLogServer",
                server_type=ServerType.PAPER,
                minecraft_version=MinecraftVersion.parse("1.20.4"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments([]),
                properties=ServerProperties(PortNumber(25565)),
                deployment=ServerDeployment(
                    location_type=LocationType.LOCAL,
                    root_path=str(server_dir),
                    working_directory=".",
                    startup_jar="server.jar",
                ),
            )
            server_id = str(server.id)
            await repo.save(server)
            await session.commit()

        handler = GetServerConsoleHandler()
        result = await handler.handle(GetServerConsoleQuery(server_id=server_id, tail=10))
        assert result.lines == ["No log file exists on disk yet"]

    @pytest.mark.asyncio
    async def test_start_server_heals_stale_deployment_port_and_surfaces_fast_crash_logs(
        self, tmp_path: Path
    ) -> None:
        from unittest.mock import AsyncMock, patch

        from app.core.event_bus import EventBus
        from app.core.exceptions import ProviderError
        from app.modules.server.application.commands.start_server import (
            StartServerCommand,
            StartServerHandler,
        )
        from app.modules.server.domain.aggregate import ServerStatus
        from app.modules.server.infrastructure.models import ServerModel

        server_dir = tmp_path / "srv_fast_crash"
        server_dir.mkdir(parents=True, exist_ok=True)
        (server_dir / "server.jar").write_bytes(b"fake-jar")
        (server_dir / "eula.txt").write_text("eula=true\n", encoding="utf-8")
        (server_dir / "server.properties").write_text(
            "server-port=25566\nenable-rcon=true\nrcon.port=25575\nrcon.password=testpw\n",
            encoding="utf-8",
        )

        sid = "srv-fast-crash-25566"
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = Server.create(
                server_id=ServerId(sid),
                name="CrashServer2",
                server_type=ServerType.PURPUR,
                minecraft_version=MinecraftVersion.parse("1.21.11"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments([]),
                properties=ServerProperties(PortNumber(25566)),
                deployment=ServerDeployment(
                    location_type=LocationType.DOCKER,
                    root_path=str(server_dir),
                    working_directory=".",
                    startup_jar="server.jar",
                ),
            )
            await repo.save(server)
            # Simulate legacy stale deployment_port=25565 while port=25566
            row = await session.get(ServerModel, sid)
            assert row is not None
            row.deployment_port = 25565
            await session.commit()

        mock_provider = AsyncMock()
        mock_provider.name = "docker"
        mock_provider.prepare_environment = AsyncMock()
        mock_provider.start = AsyncMock(
            side_effect=ProviderError(
                "docker",
                "start",
                "Container start failed: Bind for 127.0.0.1:25575 failed: "
                "port is already allocated\n"
                "failed to start containers: onx-srv-fast-crash-25566",
            )
        )

        start_handler = StartServerHandler(EventBus(), provider=mock_provider)
        with patch(
            "app.modules.server.application.commands.start_server._port_is_listening",
            return_value=False,
        ):
            res = await start_handler.handle(StartServerCommand(server_id=sid))

        assert res.success is False
        assert res.error_code == "PROVIDER_START_FAILED"

        # Stale deployment_port must be auto-healed to 25566
        async with database.session_factory() as session:
            row = await session.get(ServerModel, sid)
            assert row is not None
            assert row.status == ServerStatus.CRASHED.value
            assert row.port == 25566
            assert row.deployment_port == 25566

        # Console query must surface the full error immediately (not blank / placeholder)
        console_handler = GetServerConsoleHandler()
        console = await console_handler.handle(GetServerConsoleQuery(server_id=sid, tail=100))
        assert len(console.lines) == 2
        assert console.lines[0].startswith("[ERROR] docker start failed:")
        assert "Bind for 127.0.0.1:25575 failed: port is already allocated" in console.lines[0]
        assert "failed to start containers: onx-srv-fast-crash-25566" in console.lines[1]

    @pytest.mark.asyncio
    async def test_console_surfaces_crash_activity_log_when_evidence_bundle_missing(
        self, tmp_path: Path
    ) -> None:
        import json

        from app.modules.activity.infrastructure.models import ServerActivityLogModel
        from app.modules.server.domain.aggregate import ServerStatus
        from app.modules.server.infrastructure.models import ServerModel

        server_dir = tmp_path / "srv_legacy_crash"
        server_dir.mkdir(parents=True, exist_ok=True)
        sid = "srv-legacy-crash-1"

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = Server.create(
                server_id=ServerId(sid),
                name="LegacyCrash",
                server_type=ServerType.PURPUR,
                minecraft_version=MinecraftVersion.parse("1.21.11"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments([]),
                properties=ServerProperties(PortNumber(25566)),
                deployment=ServerDeployment(
                    location_type=LocationType.DOCKER,
                    root_path=str(server_dir),
                    working_directory=".",
                    startup_jar="server.jar",
                ),
            )
            await repo.save(server)
            row = await session.get(ServerModel, sid)
            assert row is not None
            row.status = ServerStatus.CRASHED.value
            row.external_id = ""
            session.add(
                ServerActivityLogModel(
                    id="act-crash-1",
                    server_id=sid,
                    timestamp=1795517943.3,
                    event_type="server.crashed",
                    actor_type="system",
                    summary="Server crashed (exit code: -1)",
                    details_json=json.dumps(
                        {
                            "exit_code": -1,
                            "last_log_lines": [
                                "docker start failed: Container start failed: "
                                "Bind for 127.0.0.1:25575 failed: port is already allocated\n"
                                "failed to start containers: onx-test"
                            ],
                        }
                    ),
                )
            )
            await session.commit()

        handler = GetServerConsoleHandler()
        result = await handler.handle(GetServerConsoleQuery(server_id=sid, tail=100))
        assert len(result.lines) == 2
        assert result.lines[0].startswith("[ERROR] docker start failed:")
        assert "Bind for 127.0.0.1:25575 failed: port is already allocated" in result.lines[0]
        assert "failed to start containers: onx-test" in result.lines[1]
