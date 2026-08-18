from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.backup.application.commands.create_backup import CreateBackupCommand, CreateBackupHandler
from app.modules.backup.domain.aggregate import BackupJob, BackupPolicy, BackupStatus, BackupType
from app.modules.backup.infrastructure.models import BackupJobModel
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.server.application.commands.restart_server import RestartServerCommand, RestartServerHandler
from app.modules.server.application.commands.start_server import StartServerCommand, StartServerHandler
from app.modules.server.application.commands.stop_server import StopServerCommand, StopServerHandler
from app.modules.server.application.runtime_reconciliation import (
    MismatchType,
    ServerRuntimeState,
    _auto_repair,
    _detect_mismatches,
)
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.events import ServerStartingEvent
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.server.infrastructure.providers.base import (
    DeploymentResult,
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import BackupJobId, MinecraftVersion, ServerId
from app.services.backup_orchestrator import (
    BackupCancelledError,
    cancel_backup,
    clear_cancelled_backup,
    is_backup_cancelled,
)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


async def _create_server(
    server_id: str,
    status: ServerStatus = ServerStatus.STOPPED,
    with_deployment: bool = True,
) -> Server:
    deployment = None
    if with_deployment:
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path=f"/tmp/mcs-{server_id}",
            working_directory=".",
            startup_jar="server.jar",
        )
    server = Server.create(
        server_id=ServerId(server_id),
        name=f"Server-{server_id}",
        server_type=ServerType.VANILLA,
        minecraft_version=MinecraftVersion.parse("1.21"),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(),
        properties=ServerProperties(port=PortNumber(25565)),
        deployment=deployment,
    )
    if status == ServerStatus.RUNNING:
        server.start()
        server.mark_running(pid=1234, port=25565, external_id=f"mcs-{server_id}")
    elif status == ServerStatus.STARTING:
        server.start()
        server.record_runtime_starting(pid=1234, port=25565, external_id=f"mcs-{server_id}")
    server.collect_events()

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        await repo.save(server)
        await session.commit()
    return server


@pytest.mark.usefixtures("init_test_db")
class TestStartingVisibleAggregate:
    def test_record_runtime_starting_preserves_starting_status(self) -> None:
        server = Server.create(
            server_id=ServerId("agg-1"),
            name="Agg Server",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )
        server.start()
        assert server.status == ServerStatus.STARTING

        server.record_runtime_starting(
            pid=9999,
            port=25565,
            host="127.0.0.1",
            external_id="mcs-agg-1",
            start_time="2026-08-18T12:00:00Z",
        )

        assert server.status == ServerStatus.STARTING
        assert server.runtime is not None
        assert server.runtime.pid == 9999
        assert server.runtime.port == 25565
        assert server.runtime.host == "127.0.0.1"
        assert server.runtime.external_id == "mcs-agg-1"

        events = server.collect_events()
        assert any(isinstance(e, ServerStartingEvent) for e in events)

    def test_aggregate_allows_starting_to_stopping_transition(self) -> None:
        server = Server.create(
            server_id=ServerId("agg-stop-1"),
            name="Agg Server Stop",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(25565)),
        )
        server.start()
        assert server.status == ServerStatus.STARTING

        server.stop(reason="user_stop_during_starting")
        assert server.status == ServerStatus.STOPPING
        server.mark_stopped()
        assert server.status == ServerStatus.STOPPED


@pytest.mark.usefixtures("init_test_db")
class TestStartAndRestartCommandsLeaveStarting:
    @pytest.mark.asyncio
    async def test_start_command_leaves_db_status_starting(self, event_bus: EventBus) -> None:
        await _create_server("srv-start-1", status=ServerStatus.STOPPED)

        mock_provider = AsyncMock()
        mock_provider.provider_type = "local"
        mock_provider.start.return_value = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=4567,
            metadata={"session_name": "mcs-srv-start-1"},
        )

        handler = StartServerHandler(event_bus)
        with patch("app.modules.server.application.commands.start_server.provider_factory.get", return_value=mock_provider), \
             patch("app.modules.server.application.commands.start_server.RuntimeSupervisor.start_for"):
            result = await handler.handle(StartServerCommand(server_id="srv-start-1"))

        assert result.success is True
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            saved = await repo.get(ServerId("srv-start-1"))
            assert saved.status == ServerStatus.STARTING
            assert saved.runtime is not None
            assert saved.runtime.pid == 4567

    @pytest.mark.asyncio
    async def test_restart_command_leaves_db_status_starting(self, event_bus: EventBus) -> None:
        await _create_server("srv-restart-1", status=ServerStatus.RUNNING)

        mock_provider = AsyncMock()
        mock_provider.provider_type = "local"
        mock_provider.status.return_value = ServerRuntimeStatus.STOPPED
        mock_provider.start.return_value = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=7890,
            metadata={"session_name": "mcs-srv-restart-1"},
        )

        handler = RestartServerHandler(event_bus)
        with patch("app.modules.server.application.commands.restart_server.provider_factory.get", return_value=mock_provider), \
             patch("app.modules.server.application.commands.restart_server.RuntimeSupervisor.start_for"):
            result = await handler.handle(RestartServerCommand(server_id="srv-restart-1"))

        assert result.success is True
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            saved = await repo.get(ServerId("srv-restart-1"))
            assert saved.status == ServerStatus.STARTING
            assert saved.runtime is not None
            assert saved.runtime.pid == 7890

    @pytest.mark.asyncio
    async def test_stop_command_on_starting_server_succeeds(self, event_bus: EventBus) -> None:
        await _create_server("srv-stop-starting-1", status=ServerStatus.STARTING)

        handler = StopServerHandler(event_bus)
        result = await handler.handle(StopServerCommand(server_id="srv-stop-starting-1", reason="test"))

        assert result.success is True
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            saved = await repo.get(ServerId("srv-stop-starting-1"))
            assert saved.status == ServerStatus.STOPPED

    @pytest.mark.asyncio
    async def test_restart_command_on_starting_server_succeeds(self, event_bus: EventBus) -> None:
        await _create_server("srv-restart-starting-1", status=ServerStatus.STARTING)

        mock_provider = AsyncMock()
        mock_provider.provider_type = "local"
        mock_provider.status.return_value = ServerRuntimeStatus.STOPPED
        mock_provider.start.return_value = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=7891,
            metadata={"session_name": "mcs-srv-restart-starting-1"},
        )

        handler = RestartServerHandler(event_bus)
        with patch("app.modules.server.application.commands.restart_server.provider_factory.get", return_value=mock_provider), \
             patch("app.modules.server.application.commands.restart_server.RuntimeSupervisor.start_for"):
            result = await handler.handle(RestartServerCommand(server_id="srv-restart-starting-1"))

        assert result.success is True
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            saved = await repo.get(ServerId("srv-restart-starting-1"))
            assert saved.status == ServerStatus.STARTING
            assert saved.runtime is not None
            assert saved.runtime.pid == 7891


@pytest.mark.usefixtures("init_test_db")
class TestSupervisorVerifyStartup:
    @pytest.mark.asyncio
    async def test_supervisor_verify_startup_transitions_to_running_on_ready(self) -> None:
        server = await _create_server("srv-sup-1", status=ServerStatus.STARTING)

        mock_provider = MagicMock(spec=ServerProvider)
        mock_provider.provider_type = "local"
        mock_provider.wait_ready = AsyncMock(return_value=True)
        mock_provider.verify_process = AsyncMock(return_value=True)
        mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.RUNNING)

        repo_get = AsyncMock(return_value=server)
        saved_server_holder: list[Server] = []
        async def mock_repo_save(s: Server) -> None:
            saved_server_holder.append(s)

        handle = ServerHandle(
            provider="local",
            server_id="srv-sup-1",
            external_id="mcs-srv-sup-1",
            metadata={"pid": 1234, "port": 25565, "server_name": server.name},
        )

        supervisor = RuntimeSupervisor.start_for(
            server=server,
            provider=mock_provider,
            handle=handle,
            repo_get=repo_get,
            repo_save=mock_repo_save,
            health_interval=0.1,
            startup_timeout=1.0,
        )

        await asyncio.sleep(0.3)
        await RuntimeSupervisor.stop_for(supervisor.server_id)

        assert any(s.status == ServerStatus.RUNNING for s in saved_server_holder)

    @pytest.mark.asyncio
    async def test_supervisor_verify_startup_transitions_to_running_on_deadline_passed_process_alive(self) -> None:
        server = await _create_server("srv-sup-2", status=ServerStatus.STARTING)

        mock_provider = MagicMock(spec=ServerProvider)
        mock_provider.provider_type = "local"
        # wait_ready returns False (deadline elapsed), but process is alive
        mock_provider.wait_ready = AsyncMock(return_value=False)
        mock_provider.verify_process = AsyncMock(return_value=True)
        mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.RUNNING)

        repo_get = AsyncMock(return_value=server)
        saved_server_holder: list[Server] = []
        async def mock_repo_save(s: Server) -> None:
            saved_server_holder.append(s)

        handle = ServerHandle(
            provider="local",
            server_id="srv-sup-2",
            external_id="mcs-srv-sup-2",
            metadata={"pid": 1234, "port": 25565, "server_name": server.name},
        )

        supervisor = RuntimeSupervisor(
            server=server,
            provider=mock_provider,
            handle=handle,
            repo_get=repo_get,
            repo_save=mock_repo_save,
            health_interval=0.1,
            startup_timeout=0.01,
        )

        # Execute _verify_startup directly
        await supervisor._verify_startup()

        # OQ-2 fallback: process alive after startup deadline transitions to RUNNING best-effort
        assert any(s.status == ServerStatus.RUNNING for s in saved_server_holder)

    @pytest.mark.asyncio
    async def test_supervisor_does_not_mark_running_when_stop_races_wait_ready(self) -> None:
        server = await _create_server("srv-sup-3", status=ServerStatus.STARTING)

        mock_provider = MagicMock(spec=ServerProvider)
        mock_provider.provider_type = "local"
        mock_provider.verify_process = AsyncMock(return_value=True)
        mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.STOPPED)

        wait_started = asyncio.Event()
        release = asyncio.Event()

        async def wait_ready(*, server_id=None, handle=None, timeout=None) -> bool:
            wait_started.set()
            await release.wait()
            return True

        mock_provider.wait_ready = wait_ready

        repo_get = AsyncMock(return_value=server)
        saved_server_holder: list[Server] = []
        async def mock_repo_save(s: Server) -> None:
            saved_server_holder.append(s)

        handle = ServerHandle(
            provider="local",
            server_id="srv-sup-3",
            external_id="mcs-srv-sup-3",
            metadata={"pid": 1234, "port": 25565, "server_name": server.name},
        )

        supervisor = RuntimeSupervisor.start_for(
            server=server,
            provider=mock_provider,
            handle=handle,
            repo_get=repo_get,
            repo_save=mock_repo_save,
            health_interval=0.1,
            startup_timeout=5.0,
        )

        await wait_started.wait()
        supervisor._stop_event.set()
        release.set()
        await asyncio.sleep(0.2)
        await RuntimeSupervisor.stop_for(supervisor.server_id)

        assert saved_server_holder == []

    @pytest.mark.asyncio
    async def test_supervisor_does_not_override_concurrent_stop_status(self) -> None:
        server = await _create_server("srv-sup-4", status=ServerStatus.STARTING)
        server.stop(reason="concurrent stop committed by user")
        assert server.status == ServerStatus.STOPPING

        mock_provider = MagicMock(spec=ServerProvider)
        mock_provider.provider_type = "local"
        mock_provider.wait_ready = AsyncMock(return_value=True)
        mock_provider.verify_process = AsyncMock(return_value=True)
        mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.STOPPED)

        repo_get = AsyncMock(return_value=server)
        saved_server_holder: list[Server] = []
        async def mock_repo_save(s: Server) -> None:
            saved_server_holder.append(s)

        handle = ServerHandle(
            provider="local",
            server_id="srv-sup-4",
            external_id="mcs-srv-sup-4",
            metadata={"pid": 1234, "port": 25565, "server_name": server.name},
        )

        supervisor = RuntimeSupervisor(
            server=server,
            provider=mock_provider,
            handle=handle,
            repo_get=repo_get,
            repo_save=mock_repo_save,
            health_interval=0.1,
            startup_timeout=1.0,
        )

        await supervisor._verify_startup()

        assert saved_server_holder == []


@pytest.mark.usefixtures("init_test_db")
class TestRuntimeReconciliationStarting:
    @pytest.mark.asyncio
    async def test_detects_and_repairs_db_starting_dead_to_crashed(self) -> None:
        state = ServerRuntimeState(
            server_id="srv-dead-1",
            server_name="Server-srv-dead-1",
            db_status=ServerStatus.STARTING,
            has_supervisor=False,
            supervisor_running=False,
            has_tmux=False,
            pid_alive=False,
            port_listening=False,
        )

        mismatches = _detect_mismatches(state)
        assert any(m.mismatch_type == MismatchType.DB_STARTING_DEAD for m in mismatches)

        server = await _create_server("srv-dead-1", status=ServerStatus.STARTING)
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            repaired, actions = await _auto_repair(server, state, mismatches, repo)
            assert repaired is True
            assert server.status == ServerStatus.CRASHED

    @pytest.mark.asyncio
    async def test_detects_and_repairs_db_starting_alive_to_running(self) -> None:
        state = ServerRuntimeState(
            server_id="srv-alive-1",
            server_name="Server-srv-alive-1",
            db_status=ServerStatus.STARTING,
            has_supervisor=False,
            supervisor_running=False,
            has_tmux=True,
            tmux_pid=5555,
            pid_alive=True,
            port_listening=False,  # Dropped port requirement for alive transition
            port=25565,
            external_id="mcs-srv-alive-1",
        )

        mismatches = _detect_mismatches(state)
        assert any(m.mismatch_type == MismatchType.DB_STARTING_ALIVE for m in mismatches)

        server = await _create_server("srv-alive-1", status=ServerStatus.STARTING)
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            repaired, actions = await _auto_repair(server, state, mismatches, repo)
            assert repaired is True
            assert server.status == ServerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_fresh_starting_server_is_not_falsely_crashed(self) -> None:
        state = ServerRuntimeState(
            server_id="srv-fresh-1",
            server_name="Server-srv-fresh-1",
            db_status=ServerStatus.STARTING,
            has_supervisor=False,
            supervisor_running=False,
            has_tmux=False,
            pid_alive=False,
            port_listening=False,
            start_age_seconds=5.0,  # 5 seconds old (well within 60s window)
        )

        mismatches = _detect_mismatches(state)
        # Should NOT generate DB_STARTING_DEAD mismatch during the fresh starting window
        assert not any(m.mismatch_type == MismatchType.DB_STARTING_DEAD for m in mismatches)


@pytest.mark.usefixtures("init_test_db")
class TestBackupCooperativeCancellation:
    def test_backup_status_failed_timeout_and_mark_failed_timeout(self) -> None:
        job = BackupJob(
            backup_id=BackupJobId("bkp-to-1"),
            server_id=ServerId("srv-to-1"),
            backup_type=BackupType.FULL,
            status=BackupStatus.IN_PROGRESS,
        )
        job.mark_failed_timeout("Timed out waiting for server restart")
        assert job.status == BackupStatus.FAILED_TIMEOUT
        assert job.error_message == "Timed out waiting for server restart"

    def test_cancel_backup_lifecycle(self) -> None:
        bid = "test-cancel-bid-1"
        try:
            assert not is_backup_cancelled(bid)
            cancel_backup(bid)
            assert is_backup_cancelled(bid)
        finally:
            clear_cancelled_backup(bid)
            assert not is_backup_cancelled(bid)

    @pytest.mark.asyncio
    async def test_restart_server_waits_for_backup_and_cancels_on_timeout(self, event_bus: EventBus) -> None:
        server = await _create_server("srv-bkp-restart", status=ServerStatus.RUNNING)
        bid = BackupJobId("bkp-restart-job-1")

        async with database.session_factory() as session:
            bkp_repo = SQLBackupRepository(session)
            job = BackupJob(
                backup_id=bid,
                server_id=ServerId("srv-bkp-restart"),
                backup_type=BackupType.FULL,
                status=BackupStatus.IN_PROGRESS,
            )
            await bkp_repo.save_job(job)
            await session.commit()

        mock_provider = AsyncMock()
        mock_provider.provider_type = "local"
        mock_provider.status.return_value = ServerRuntimeStatus.STOPPED
        mock_provider.start.return_value = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=9999,
            metadata={"session_name": "mcs-srv-bkp-restart"},
        )

        handler = RestartServerHandler(event_bus)
        # Patch _BACKUP_WAIT_CAP_S to 0.1s for fast test
        with patch("app.modules.server.application.commands.restart_server._BACKUP_WAIT_CAP_S", 0.1), \
             patch("app.modules.server.application.commands.restart_server.provider_factory.get", return_value=mock_provider), \
             patch("app.modules.server.application.commands.restart_server.RuntimeSupervisor.start_for"):
            result = await handler.handle(RestartServerCommand(server_id="srv-bkp-restart"))

        assert result.success is True
        assert is_backup_cancelled(str(bid))
        clear_cancelled_backup(str(bid))
