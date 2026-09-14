from __future__ import annotations

from pathlib import Path

import pytest

from app.core.persistence.db import database
from app.modules.health.application.queries.get_crash_reports import (
    GetServerCrashReportsHandler,
    GetServerCrashReportsQuery,
)
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.diagnostics import FailureCode
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


class TestGetServerCrashReports:
    @pytest.mark.asyncio
    async def test_get_crash_reports_scans_and_blames_mod(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "srv_crashed"
        crash_dir = server_dir / "crash-reports"
        crash_dir.mkdir(parents=True, exist_ok=True)

        report_content = (
            "---- Minecraft Crash Report ----\n"
            "Time: 2026-09-14 01:00:00 UTC\n"
            "Description: Exception in server tick loop\n"
            "\n"
            "net.minecraftforge.fml.ModLoadingException: Mod biomesoplenty (id biomesoplenty) "
            "encountered an error during common_setup\n"
            "\tat net.minecraftforge.fml.ModLoader.load(ModLoader.java:50)\n"
            "-- System Details --\n"
        )
        report_file = crash_dir / "crash-2026-09-14_01.00.00-server.txt"
        report_file.write_text(report_content, encoding="utf-8")

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = Server.create(
                server_id=ServerId("srv-crash-1"),
                name="CrashedServer",
                server_type=ServerType.FORGE,
                minecraft_version=MinecraftVersion.parse("1.20.1"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments([]),
                properties=ServerProperties(PortNumber(25565)),
                deployment=ServerDeployment(
                    location_type=LocationType.LOCAL,
                    root_path=str(server_dir),
                    working_directory=".",
                    startup_jar="forge.jar",
                ),
            )
            await repo.save(server)
            await session.commit()

        handler = GetServerCrashReportsHandler()
        reports = await handler.handle(GetServerCrashReportsQuery(server_id="srv-crash-1"))

        assert len(reports) == 1
        summary = reports[0]
        assert summary.filename == "crash-2026-09-14_01.00.00-server.txt"
        assert summary.failure_code == FailureCode.MOD_CRASH.value
        assert summary.blamed_mod == "biomesoplenty"
        assert "biomesoplenty" in summary.suggested_remediation
        assert "ModLoadingException" in summary.stack_trace_snippet

    @pytest.mark.asyncio
    async def test_get_crash_reports_empty_when_no_directory(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "srv_clean"
        server_dir.mkdir(parents=True, exist_ok=True)

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            server = Server.create(
                server_id=ServerId("srv-clean-1"),
                name="CleanServer",
                server_type=ServerType.PAPER,
                minecraft_version=MinecraftVersion.parse("1.20.4"),
                memory=MemoryAllocation(1024, 2048),
                java_args=JavaArguments([]),
                properties=ServerProperties(PortNumber(25565)),
                deployment=ServerDeployment(
                    location_type=LocationType.LOCAL,
                    root_path=str(server_dir),
                    working_directory=".",
                    startup_jar="paper.jar",
                ),
            )
            await repo.save(server)
            await session.commit()

        handler = GetServerCrashReportsHandler()
        reports = await handler.handle(GetServerCrashReportsQuery(server_id="srv-clean-1"))
        assert reports == []
