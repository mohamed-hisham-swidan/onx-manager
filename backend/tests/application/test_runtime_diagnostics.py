from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.persistence.db import database
from app.modules.server.application.queries.get_runtime_diagnostics import (
    GetServerRuntimeDiagnosticsHandler,
    GetServerRuntimeDiagnosticsQuery,
)
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId


@pytest.mark.usefixtures("init_test_db")
class TestRuntimeDiagnosticsUptime:
    @pytest.mark.asyncio
    async def test_supervised_running_server_uses_supervisor_uptime(self) -> None:
        server_id = ServerId("srv-diag-sup")
        server = Server.create(
            server_id=server_id,
            name="Supervised Server",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )
        server.start()
        server.mark_running(pid=1001, port=25565, host="127.0.0.1")

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        mock_supervisor = MagicMock()
        mock_supervisor.is_running = True
        mock_supervisor.uptime = 123.45
        mock_supervisor.last_heartbeat = time.time()
        mock_supervisor.start_duration = 2.5

        with (
            patch.object(RuntimeSupervisor, "get_for", return_value=mock_supervisor),
            patch.object(RuntimeSupervisor, "is_supervised", return_value=True),
            patch(
                "app.modules.server.application.runtime_ownership.RuntimeOwnershipManager"
            ) as mock_mgr,
        ):
            mock_mgr.return_value.validate_runtime = AsyncMock(return_value=MagicMock(chain=[]))
            mock_mgr.return_value.detect_owner_conflicts = AsyncMock(return_value=[])

            handler = GetServerRuntimeDiagnosticsHandler()
            result = await handler.handle(
                GetServerRuntimeDiagnosticsQuery(server_id="srv-diag-sup")
            )

        assert result.data["uptime_seconds"] == 123.45
        assert result.data["supervised"] is True

    @pytest.mark.asyncio
    async def test_unsupervised_running_server_derives_uptime_from_start_time(self) -> None:
        server_id = ServerId("srv-diag-unsup")
        server = Server.create(
            server_id=server_id,
            name="Unsupervised Server",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )
        server.start()
        server.mark_running(pid=1002, port=25565, host="127.0.0.1")
        # Set start_time to 50 seconds ago
        server.runtime.start_time = time.time() - 50.0

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        with (
            patch.object(RuntimeSupervisor, "get_for", return_value=None),
            patch.object(RuntimeSupervisor, "is_supervised", return_value=False),
            patch(
                "app.modules.server.application.runtime_ownership.RuntimeOwnershipManager"
            ) as mock_mgr,
        ):
            mock_mgr.return_value.validate_runtime = AsyncMock(return_value=MagicMock(chain=[]))
            mock_mgr.return_value.detect_owner_conflicts = AsyncMock(return_value=[])

            handler = GetServerRuntimeDiagnosticsHandler()
            result = await handler.handle(
                GetServerRuntimeDiagnosticsQuery(server_id="srv-diag-unsup")
            )

        assert 48.0 <= result.data["uptime_seconds"] <= 55.0
        assert result.data["supervised"] is False

    @pytest.mark.asyncio
    async def test_stopped_server_returns_zero_uptime(self) -> None:
        server_id = ServerId("srv-diag-stopped")
        server = Server.create(
            server_id=server_id,
            name="Stopped Server",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(server)
            await session.commit()

        with (
            patch.object(RuntimeSupervisor, "get_for", return_value=None),
            patch.object(RuntimeSupervisor, "is_supervised", return_value=False),
            patch(
                "app.modules.server.application.runtime_ownership.RuntimeOwnershipManager"
            ) as mock_mgr,
        ):
            mock_mgr.return_value.validate_runtime = AsyncMock(return_value=MagicMock(chain=[]))
            mock_mgr.return_value.detect_owner_conflicts = AsyncMock(return_value=[])

            handler = GetServerRuntimeDiagnosticsHandler()
            result = await handler.handle(
                GetServerRuntimeDiagnosticsQuery(server_id="srv-diag-stopped")
            )

        assert result.data["uptime_seconds"] == 0.0
