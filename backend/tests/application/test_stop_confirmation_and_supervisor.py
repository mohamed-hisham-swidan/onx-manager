from __future__ import annotations

import asyncio
import contextlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.health.infrastructure.models  # noqa: F401
from app.core.command_bus import CommandResult
from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.exceptions import ServerNotFoundError
from app.core.persistence.db import database
from app.modules.server.application.commands.delete_server import (
    DeleteServerCommand,
    DeleteServerHandler,
)
from app.modules.server.application.commands.restart_server import (
    RestartServerCommand,
    RestartServerHandler,
)
from app.modules.server.application.commands.stop_server import (
    StopServerCommand,
    StopServerHandler,
    is_stop_confirmed,
)
from app.modules.server.application.reconciliation import reconcile_servers
from app.modules.server.application.services.installer_provisioner import ProvisioningRegistry
from app.modules.server.application.supervisor import RuntimeSupervisor
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.diagnostics import FailureCode, RuntimeDiagnostics
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
    ServerHandle,
    ServerRuntimeStatus,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId


async def _create_test_server(
    server_id: str,
    status: ServerStatus = ServerStatus.RUNNING,
    name: str = "TestSrv",
    port: int = 25565,
    external_id: str = "ext-123",
    pid: int = 1234,
) -> Server:
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        root_path = os.path.join(AppSettings().servers_data_dir, server_id)
        os.makedirs(root_path, exist_ok=True)
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path=root_path,
            working_directory=".",
            startup_jar="server.jar",
        )
        server = Server.create(
            server_id=ServerId(server_id),
            name=name,
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments(),
            properties=ServerProperties(port=PortNumber(port)),
            deployment=deployment,
        )
        if status in (
            ServerStatus.STARTING,
            ServerStatus.RUNNING,
            ServerStatus.STOPPING,
            ServerStatus.STOPPED,
        ):
            server.start()
            server.record_runtime_starting(pid=pid, port=port, external_id=external_id)
            if status in (ServerStatus.RUNNING, ServerStatus.STOPPING, ServerStatus.STOPPED):
                server.mark_running(pid=pid, port=port, external_id=external_id)
                if status == ServerStatus.STOPPING:
                    server.stop(reason="test stopping")
                elif status == ServerStatus.STOPPED:
                    server.stop(reason="test stopped")
                    server.mark_stopped()
        elif status == ServerStatus.PROVISIONING:
            server.begin_provisioning()

        server.collect_events()
        await repo.save(server)
        await session.commit()
        return server


async def _get_server(server_id: str) -> Server:
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        return await repo.get(ServerId(server_id))


# ---------------------------------------------------------------------------
# 1. is_stop_confirmed contract
# ---------------------------------------------------------------------------


def test_is_stop_confirmed_contract() -> None:
    assert is_stop_confirmed(None) is False
    assert is_stop_confirmed(CommandResult(success=False, data={})) is False
    assert is_stop_confirmed(CommandResult(success=True, data="string_data")) is False
    assert is_stop_confirmed(CommandResult(success=True, data={"stop_confirmed": False})) is False

    # Confirmed True with warnings -> False
    assert (
        is_stop_confirmed(
            CommandResult(
                success=True,
                data={"stop_confirmed": True, "warnings": ["port took 3s"]},
            )
        )
        is False
    )

    # Confirmed True with provider_errors -> False
    assert (
        is_stop_confirmed(
            CommandResult(
                success=True,
                data={"stop_confirmed": True, "provider_errors": ["status timeout"]},
            )
        )
        is False
    )

    # Clean confirmation -> True
    assert (
        is_stop_confirmed(
            CommandResult(
                success=True,
                data={
                    "stop_confirmed": True,
                    "warnings": [],
                    "provider_errors": [],
                },
            )
        )
        is True
    )


# ---------------------------------------------------------------------------
# 2. StopServerHandler Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_server_confirmed_success() -> None:
    await _create_test_server("srv-stop-1", status=ServerStatus.RUNNING)
    event_bus = EventBus()
    handler = StopServerHandler(event_bus)

    mock_provider = AsyncMock()
    mock_provider.name = "local"
    mock_provider.stop = AsyncMock(return_value=None)
    mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.STOPPED)

    with (
        patch(
            "app.modules.server.application.commands.stop_server.provider_factory.get",
            return_value=mock_provider,
        ),
        patch(
            "app.modules.server.application.commands.stop_server._port_is_listening",
            return_value=False,
        ),
    ):
        result = await handler.handle(StopServerCommand(server_id="srv-stop-1"))

    assert result.success is True
    assert result.data["stop_confirmed"] is True
    assert result.data["status"] == "stopped"

    saved = await _get_server("srv-stop-1")
    assert saved.status == ServerStatus.STOPPED


@pytest.mark.asyncio
async def test_stop_server_reverts_to_running_when_runtime_active() -> None:
    await _create_test_server("srv-stop-2", status=ServerStatus.RUNNING)
    event_bus = EventBus()
    handler = StopServerHandler(event_bus)

    mock_provider = AsyncMock()
    mock_provider.name = "local"
    mock_provider.stop = AsyncMock(return_value=None)
    mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.RUNNING)

    with (
        patch(
            "app.modules.server.application.commands.stop_server.provider_factory.get",
            return_value=mock_provider,
        ),
        patch(
            "app.modules.server.application.commands.stop_server._port_is_listening",
            return_value=False,
        ),
        patch.object(RuntimeSupervisor, "start_for", MagicMock()),
    ):
        result = await handler.handle(StopServerCommand(server_id="srv-stop-2"))

    assert result.success is False
    assert result.error_code == "SERVER_STOP_FAILED"
    assert result.data["stop_confirmed"] is False
    assert result.data["status"] == "running"

    saved = await _get_server("srv-stop-2")
    assert saved.status == ServerStatus.RUNNING
    assert saved.runtime.external_id == "ext-123"
    assert saved.runtime.pid == 1234


@pytest.mark.asyncio
async def test_stop_server_unconfirmed_stays_stopping() -> None:
    # Server has no external_id -> no runtime handle
    await _create_test_server("srv-stop-3", status=ServerStatus.RUNNING, external_id="")
    event_bus = EventBus()
    handler = StopServerHandler(event_bus)

    mock_provider = AsyncMock()
    mock_provider.name = "local"

    with patch(
        "app.modules.server.application.commands.stop_server.provider_factory.get",
        return_value=mock_provider,
    ):
        result = await handler.handle(StopServerCommand(server_id="srv-stop-3"))

    assert result.success is False
    assert result.error_code == "SERVER_STOP_UNCONFIRMED"
    assert result.data["stop_confirmed"] is False
    assert result.data["status"] == "stopping"

    saved = await _get_server("srv-stop-3")
    assert saved.status == ServerStatus.STOPPING


@pytest.mark.asyncio
async def test_stop_server_reentry_from_stopping() -> None:
    await _create_test_server("srv-stop-4", status=ServerStatus.STOPPING)
    event_bus = EventBus()
    handler = StopServerHandler(event_bus)

    mock_provider = AsyncMock()
    mock_provider.name = "local"
    mock_provider.stop = AsyncMock(return_value=None)
    mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.STOPPED)

    with (
        patch(
            "app.modules.server.application.commands.stop_server.provider_factory.get",
            return_value=mock_provider,
        ),
        patch(
            "app.modules.server.application.commands.stop_server._port_is_listening",
            return_value=False,
        ),
    ):
        result = await handler.handle(StopServerCommand(server_id="srv-stop-4"))

    assert result.success is True
    assert result.data["stop_confirmed"] is True
    assert result.data["status"] == "stopped"

    saved = await _get_server("srv-stop-4")
    assert saved.status == ServerStatus.STOPPED


# ---------------------------------------------------------------------------
# 3. RestartServerHandler Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_server_aborts_on_unconfirmed_stop() -> None:
    await _create_test_server("srv-restart-1", status=ServerStatus.RUNNING)
    event_bus = EventBus()
    handler = RestartServerHandler(event_bus)

    mock_provider = AsyncMock()
    mock_provider.name = "local"
    mock_provider.stop = AsyncMock(return_value=None)
    # Status check indicates runtime is still RUNNING
    mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.RUNNING)

    with (
        patch(
            "app.modules.server.application.commands.restart_server.provider_factory.get",
            return_value=mock_provider,
        ),
        patch(
            "app.modules.server.application.commands.restart_server._port_is_listening",
            return_value=False,
        ),
        patch(
            "app.modules.server.application.commands.restart_server.consume_pending_restore",
            AsyncMock(),
        ) as mock_restore,
    ):
        result = await handler.handle(RestartServerCommand(server_id="srv-restart-1"))

    assert result.success is False
    assert result.error_code == "RESTART_STOP_FAILED"
    mock_restore.assert_not_called()

    saved = await _get_server("srv-restart-1")
    assert saved.status == ServerStatus.RUNNING


@pytest.mark.asyncio
async def test_restart_server_cleans_up_on_provider_start_timeout() -> None:
    await _create_test_server("srv-restart-2", status=ServerStatus.RUNNING)
    event_bus = EventBus()
    handler = RestartServerHandler(event_bus)

    mock_provider = AsyncMock()
    mock_provider.name = "local"
    # Stop succeeds
    mock_provider.stop = AsyncMock(return_value=None)
    mock_provider.destroy = AsyncMock(return_value=None)
    # Provider start times out
    mock_provider.start = AsyncMock(side_effect=TimeoutError("Spawn timed out"))
    # Cleanup status returns STOPPED
    mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.STOPPED)

    with (
        patch(
            "app.modules.server.application.commands.restart_server.provider_factory.get",
            return_value=mock_provider,
        ),
        patch(
            "app.modules.server.application.commands.restart_server._port_is_listening",
            return_value=False,
        ),
        patch(
            "app.modules.server.application.commands.restart_server.consume_pending_restore",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.modules.server.application.commands.restart_server.consume_pending_plugin_deletions",
            AsyncMock(return_value=None),
        ),
    ):
        result = await handler.handle(RestartServerCommand(server_id="srv-restart-2"))

    assert result.success is False
    assert result.error_code == "STARTUP_TIMEOUT"

    # Verifies cleanup stop and destroy were called
    mock_provider.destroy.assert_called()
    saved = await _get_server("srv-restart-2")
    assert saved.status == ServerStatus.STOPPED


# ---------------------------------------------------------------------------
# 4. DeleteServerHandler & ProvisioningRegistry Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_server_during_provisioning_cancels_registry_task() -> None:
    await _create_test_server("srv-del-1", status=ServerStatus.PROVISIONING)
    event_bus = EventBus()
    handler = DeleteServerHandler(event_bus)

    async def _dummy_task_body():
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(60.0)

    task = asyncio.create_task(_dummy_task_body())
    ProvisioningRegistry.register_task("srv-del-1", task)

    result = await handler.handle(DeleteServerCommand(server_id="srv-del-1"))
    assert result.success is True
    assert task.cancelled() or task.done()

    # DB record is deleted
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        with pytest.raises(ServerNotFoundError):
            await repo.get(ServerId("srv-del-1"))


@pytest.mark.asyncio
async def test_delete_server_aborts_if_runtime_still_running() -> None:
    await _create_test_server("srv-del-2", status=ServerStatus.RUNNING)
    event_bus = EventBus()
    handler = DeleteServerHandler(event_bus)

    mock_provider = AsyncMock()
    mock_provider.name = "local"
    # Even after stop & destroy, provider reports still RUNNING
    mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.RUNNING)
    mock_provider.destroy = AsyncMock(return_value=None)

    with (
        patch(
            "app.modules.server.application.commands.delete_server.default_provider_factory.get",
            return_value=mock_provider,
        ),
        patch(
            "app.modules.server.application.commands.stop_server.provider_factory.get",
            return_value=mock_provider,
        ),
        patch(
            "app.modules.server.application.commands.stop_server._port_is_listening",
            return_value=False,
        ),
    ):
        result = await handler.handle(DeleteServerCommand(server_id="srv-del-2"))

    assert result.success is False
    assert result.error_code == "DELETE_STOP_NOT_CONFIRMED"
    mock_provider.destroy.assert_not_called()

    # Server was not deleted from DB
    saved = await _get_server("srv-del-2")
    assert saved is not None


# ---------------------------------------------------------------------------
# 5. RuntimeSupervisor Crash Stop & Save Self-Heal Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_handle_crash_stops_still_running_runtime() -> None:
    server = await _create_test_server("srv-sup-1", status=ServerStatus.RUNNING)
    mock_provider = AsyncMock()
    mock_provider.status = AsyncMock(return_value=ServerRuntimeStatus.RUNNING)
    mock_provider.stop = AsyncMock(return_value=None)
    handle = ServerHandle(provider="local", server_id="srv-sup-1", external_id="onx-srv-sup-1")

    supervisor = RuntimeSupervisor(
        server=server,
        provider=mock_provider,
        handle=handle,
        repo_get=lambda sid: _get_server(str(sid)),
        repo_save=AsyncMock(),
    )

    diag = RuntimeDiagnostics(exit_code=-1, failure_code=FailureCode.RUNTIME_PROCESS_LOST)
    await supervisor._handle_crash(diag)

    # Provider stop was called during crash handling
    mock_provider.stop.assert_awaited()


@pytest.mark.asyncio
async def test_supervisor_persist_running_self_heal() -> None:
    server = await _create_test_server("srv-sup-2", status=ServerStatus.STARTING)
    mock_provider = AsyncMock()
    mock_provider.verify_process = AsyncMock(return_value=True)
    mock_provider.get_address = AsyncMock(return_value="127.0.0.1")
    handle = ServerHandle(provider="local", server_id="srv-sup-2", external_id="onx-srv-sup-2")

    save_attempts = 0

    async def _failing_repo_save(s: Server) -> None:
        nonlocal save_attempts
        save_attempts += 1
        if save_attempts < 4:
            raise RuntimeError("Transient DB lock")
        # 4th attempt (self-heal) succeeds
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            await repo.save(s)
            await session.commit()

    supervisor = RuntimeSupervisor(
        server=server,
        provider=mock_provider,
        handle=handle,
        repo_get=lambda sid: _get_server(str(sid)),
        repo_save=_failing_repo_save,
    )

    # Initial 3 attempts fail
    success = await supervisor._persist_running_transition()
    assert success is False
    assert supervisor._running_persisted is False

    # In health check, it detects not _running_persisted and self-heals
    await supervisor._health_check()
    assert supervisor._running_persisted is True
    saved = await _get_server("srv-sup-2")
    assert saved.status == ServerStatus.RUNNING


# ---------------------------------------------------------------------------
# 6. Reconcile Servers for STOPPING State
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_stopping_server_outcomes() -> None:
    # Server A: STOPPING, provider says STOPPED -> marks STOPPED
    await _create_test_server("srv-rec-a", status=ServerStatus.STOPPING)
    # Server B: STOPPING, provider says RUNNING -> reverts to RUNNING
    await _create_test_server("srv-rec-b", status=ServerStatus.STOPPING)
    # Server C: STOPPING, provider says ERROR -> remains STOPPING
    await _create_test_server("srv-rec-c", status=ServerStatus.STOPPING)

    async def _mock_status(handle: ServerHandle) -> ServerRuntimeStatus:
        if handle.server_id == "srv-rec-a":
            return ServerRuntimeStatus.STOPPED
        if handle.server_id == "srv-rec-b":
            return ServerRuntimeStatus.RUNNING
        return ServerRuntimeStatus.ERROR

    mock_provider = AsyncMock()
    mock_provider.name = "local"
    mock_provider.status = _mock_status

    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        with (
            patch(
                "app.modules.server.application.reconciliation.provider_factory.get",
                return_value=mock_provider,
            ),
            patch.object(RuntimeSupervisor, "start_for", MagicMock()),
        ):
            results = await reconcile_servers(repo)
            await session.commit()

    res_a = next(r for r in results if r["server_id"] == "srv-rec-a")
    assert res_a["new_status"] == "stopped"

    res_b = next(r for r in results if r["server_id"] == "srv-rec-b")
    assert res_b["new_status"] == "running"

    res_c = next(r for r in results if r["server_id"] == "srv-rec-c")
    assert res_c["new_status"] == "stopping"

    saved_a = await _get_server("srv-rec-a")
    assert saved_a.status == ServerStatus.STOPPED

    saved_b = await _get_server("srv-rec-b")
    assert saved_b.status == ServerStatus.RUNNING

    saved_c = await _get_server("srv-rec-c")
    assert saved_c.status == ServerStatus.STOPPING
