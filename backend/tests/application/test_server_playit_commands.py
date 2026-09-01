"""Application-layer tests for Multi-Server Playit exposure and Assisted Setup (Batch 7.3a).

Adheres to strict test safety standards:
  - os.kill / os.killpg hermetically mocked
  - Safe sentinel mock PIDs (99999) only
  - Guaranteed try/finally: await supervisor.stop() cleanup
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.modules.auth.infrastructure.models  # noqa: F401
import app.modules.exposure.infrastructure.models  # noqa: F401
import app.modules.server.infrastructure.models  # noqa: F401
from app.core.config import init_active_panel_bind
from app.core.event_bus import EventBus
from app.core.exceptions import ValidationError
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.settings_store import init_settings_store
from app.modules.exposure.application.commands import (
    CreateExposureTargetCommand,
    CreateExposureTargetHandler,
    DisableServerExposureCommand,
    DisableServerExposureHandler,
    EnableServerExposureCommand,
    EnableServerExposureHandler,
    SetPanelExposureCommand,
    SetPanelExposureHandler,
    UpdateExposureTargetCommand,
    UpdateExposureTargetHandler,
    _handle_playit_claimed_secret,
    _persist_playit_status,
    _reconcile_playit_tunnels,
    compute_desired_agent_running,
)
from app.modules.exposure.domain.value_objects import (
    AgentProcessStatus,
    ExposureStatus,
    exposure_status_to_process_status,
)
from app.modules.exposure.infrastructure.playit_agent import (
    PlayitAgentSupervisor,
    get_playit_supervisor,
    reset_playit_supervisor,
)
from app.modules.exposure.infrastructure.playit_api import (
    PlayitAllocationFullError,
    PlayitRundataDto,
    PlayitTunnelDto,
)
from app.modules.exposure.infrastructure.repository import (
    SQLHostAgentRepository,
    SQLServerExposureRepository,
)
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

pytestmark = pytest.mark.asyncio

SAFE_SENTINEL_PID = 99999


@pytest.fixture(autouse=True)
def _mock_os_signals():
    with (
        patch("os.kill") as mock_kill,
        patch("os.killpg", create=True) as mock_killpg,
        patch("os.getpgid", return_value=SAFE_SENTINEL_PID, create=True),
    ):
        yield mock_kill, mock_killpg


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path, monkeypatch):
    test_yaml = tmp_path / "settings.yaml"
    monkeypatch.setattr("app.core.settings_store._SETTINGS_FILE", test_yaml)
    init_settings_store(test_yaml)
    init_active_panel_bind("127.0.0.1", 8000)

    test_db = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{test_db}")
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    database._engine = engine
    database._session_factory = session_factory

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await get_playit_supervisor().stop()
    reset_playit_supervisor()

    yield

    await get_playit_supervisor().stop()
    reset_playit_supervisor()
    await engine.dispose()


def _mock_subprocess(pid: int = SAFE_SENTINEL_PID):
    proc = AsyncMock()
    proc.pid = pid
    proc.returncode = None
    proc.wait = AsyncMock(return_value=0)
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.stdout = AsyncMock(readline=AsyncMock(return_value=b""))
    proc.stderr = AsyncMock(readline=AsyncMock(return_value=b""))
    return proc


async def _seed_server(server_id: str, name: str, port: int) -> None:
    async with UnitOfWork() as uow:
        repo = SQLServerRepository(uow.session)
        server = Server.create(
            server_id=ServerId(server_id),
            name=name,
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.21.4"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments([]),
            properties=ServerProperties(port=PortNumber(port)),
        )
        await repo.save(server)
        await uow.commit()


async def _seed_claimed_agent(_tmp_path=None) -> None:
    from app.modules.exposure.application.commands import _panel_encryption

    ciphertext = _panel_encryption().encrypt(b"valid-agent-secret")
    async with UnitOfWork() as uow:
        repo = SQLHostAgentRepository(uow.session)
        agent = await repo.get()
        agent.store_secret(ciphertext)
        await repo.save(agent)
        await uow.commit()


class TestMultiServerPlayitExposure:
    async def test_concurrent_activation_shares_single_process(self, tmp_path) -> None:
        """Decision 5.1: Multiple servers enabling exposure share 1 supervisor process."""
        await _seed_claimed_agent(tmp_path)
        await _seed_server("srv-1", "Server 1", 25565)
        await _seed_server("srv-2", "Server 2", 25566)

        event_bus = EventBus()
        handler = EnableServerExposureHandler(event_bus)
        proc = _mock_subprocess()

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            res1 = await handler.handle(EnableServerExposureCommand(server_id="srv-1"))
            res2 = await handler.handle(EnableServerExposureCommand(server_id="srv-2"))

            assert res1.success is True
            assert res2.success is True
            assert res1.data["desired_state"] == "ENABLED"
            assert res2.data["desired_state"] == "ENABLED"
            assert res1.data["aggregate_status"] in ("STARTING", "ACTIVE")
            assert res2.data["aggregate_status"] in ("STARTING", "ACTIVE")

            # Assisted setup returned
            target1 = res1.data["targets"][0]
            assert target1["local_port"] == 25565
            assert target1["public_address"] is None
            assert target1["dashboard_url"] == "https://playit.gg/manage"
            assert "127.0.0.1:25565" in target1["setup_instructions"]

            # Subprocess spawned exactly once
            assert mock_exec.call_count == 1
            supervisor = get_playit_supervisor()
            assert supervisor.is_running is True

    async def test_independent_deactivation_keeps_agent_running(self, tmp_path) -> None:
        """Decision 5.2: Deactivating Server 1 does not terminate agent while Server 2 is active."""
        await _seed_claimed_agent(tmp_path)
        await _seed_server("srv-1", "Server 1", 25565)
        await _seed_server("srv-2", "Server 2", 25566)

        event_bus = EventBus()
        enable_handler = EnableServerExposureHandler(event_bus)
        disable_handler = DisableServerExposureHandler(event_bus)
        proc = _mock_subprocess()

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            await enable_handler.handle(EnableServerExposureCommand(server_id="srv-1"))
            await enable_handler.handle(EnableServerExposureCommand(server_id="srv-2"))

            # Disable Server 1
            res_dis1 = await disable_handler.handle(DisableServerExposureCommand(server_id="srv-1"))
            assert res_dis1.success is True
            assert res_dis1.data["desired_state"] == "DISABLED"
            assert res_dis1.data["aggregate_status"] == "DISABLED"

            # Supervisor remains active
            supervisor = get_playit_supervisor()
            assert supervisor.is_running is True

            async with UnitOfWork() as uow:
                agent_repo = SQLHostAgentRepository(uow.session)
                agent = await agent_repo.get()
                assert agent.desired_agent_running is True

    async def test_last_target_teardown_stops_agent(self, tmp_path) -> None:
        """Decision 5.3: Deactivating the final server stops the host agent."""
        await _seed_claimed_agent(tmp_path)
        await _seed_server("srv-1", "Server 1", 25565)
        await _seed_server("srv-2", "Server 2", 25566)

        event_bus = EventBus()
        enable_handler = EnableServerExposureHandler(event_bus)
        disable_handler = DisableServerExposureHandler(event_bus)
        proc = _mock_subprocess()

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            await enable_handler.handle(EnableServerExposureCommand(server_id="srv-1"))
            await enable_handler.handle(EnableServerExposureCommand(server_id="srv-2"))

            await disable_handler.handle(DisableServerExposureCommand(server_id="srv-1"))
            await disable_handler.handle(DisableServerExposureCommand(server_id="srv-2"))

            supervisor = get_playit_supervisor()
            assert supervisor.is_running is False
            assert supervisor.status == ExposureStatus.STOPPED

            async with UnitOfWork() as uow:
                agent_repo = SQLHostAgentRepository(uow.session)
                agent = await agent_repo.get()
                assert agent.desired_agent_running is False

    async def test_cross_subsystem_panel_and_server_sharing(self, tmp_path) -> None:
        """Decision 5.4: Panel playit_http and game server playit share the supervisor."""
        await _seed_claimed_agent(tmp_path)
        await _seed_server("srv-1", "Server 1", 25565)

        event_bus = EventBus()
        server_enable = EnableServerExposureHandler(event_bus)
        server_disable = DisableServerExposureHandler(event_bus)
        panel_handler = SetPanelExposureHandler(event_bus)
        proc = _mock_subprocess()

        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            # Enable panel playit_http
            panel_res = await panel_handler.handle(
                SetPanelExposureCommand(method="playit_http", desired_state="ENABLED")
            )
            assert panel_res.success is True
            assert mock_exec.call_count == 1

            # Enable server playit exposure (shares same process)
            srv_res = await server_enable.handle(EnableServerExposureCommand(server_id="srv-1"))
            assert srv_res.success is True
            assert mock_exec.call_count == 1  # No second process spawned

            # Disable panel exposure -> agent remains running because server exposure is active
            await panel_handler.handle(
                SetPanelExposureCommand(method="none", desired_state="DISABLED")
            )
            supervisor = get_playit_supervisor()
            assert supervisor.is_running is True

            # Disable server exposure -> agent stops
            await server_disable.handle(DisableServerExposureCommand(server_id="srv-1"))
            assert supervisor.is_running is False

    async def test_manual_public_address_update_path(self) -> None:
        """Decision 5.5: Operator attaches manual public address to target."""
        await _seed_server("srv-1", "Server 1", 25565)
        event_bus = EventBus()
        create_target = CreateExposureTargetHandler(event_bus)
        update_target = UpdateExposureTargetHandler(event_bus)

        # Create target
        t_res = await create_target.handle(CreateExposureTargetCommand(server_id="srv-1"))
        assert t_res.success is True
        target_id = t_res.data["id"]
        assert t_res.data["public_address"] is None

        # Update target with valid address
        u_res = await update_target.handle(
            UpdateExposureTargetCommand(
                server_id="srv-1",
                target_id=target_id,
                public_address="mc.playit.gg:12345",
            )
        )
        assert u_res.success is True
        assert u_res.data["public_address"] == "mc.playit.gg:12345"

        # Invalid address format rejected
        with pytest.raises(ValidationError):
            await update_target.handle(
                UpdateExposureTargetCommand(
                    server_id="srv-1",
                    target_id=target_id,
                    public_address="invalid address with spaces!!!",
                )
            )

    async def test_unclaimed_agent_exposure_transitions_to_claim_required(self) -> None:
        """Enabling exposure when agent is unclaimed sets CLAIM_REQUIRED."""
        await _seed_server("srv-1", "Server 1", 25565)
        event_bus = EventBus()
        handler = EnableServerExposureHandler(event_bus)
        proc = _mock_subprocess()

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            res = await handler.handle(EnableServerExposureCommand(server_id="srv-1"))
            assert res.success is True
            assert res.data["aggregate_status"] == "CLAIM_REQUIRED"
            target = res.data["targets"][0]
            assert target["status"] == "CLAIM_REQUIRED"
            assert target["error_code"] == "CLAIM_REQUIRED"


class TestPlayitSupervisorIdempotency:
    async def test_concurrent_start_idempotency(self) -> None:
        """Decision 1: Concurrent supervisor start calls do not create multiple processes."""
        supervisor = PlayitAgentSupervisor()
        proc = _mock_subprocess()

        try:
            with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
                # Dispatch 5 start calls concurrently
                await asyncio.gather(
                    supervisor.start(secret=b"secret-1"),
                    supervisor.start(secret=b"secret-1"),
                    supervisor.start(secret=b"secret-1"),
                    supervisor.start(secret=b"secret-1"),
                    supervisor.start(secret=b"secret-1"),
                )

                assert supervisor.is_running is True
                assert mock_exec.call_count == 1
        finally:
            await supervisor.stop()


class TestUnifiedDesiredAgentRunningComputation:
    async def test_compute_desired_agent_running(self, tmp_path) -> None:
        """Decision 2: compute_desired_agent_running evaluates server and panel states."""
        await _seed_claimed_agent(tmp_path)
        await _seed_server("srv-1", "Server 1", 25565)

        event_bus = EventBus()
        server_enable = EnableServerExposureHandler(event_bus)
        server_disable = DisableServerExposureHandler(event_bus)
        panel_handler = SetPanelExposureHandler(event_bus)
        proc = _mock_subprocess()

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            async with UnitOfWork() as uow:
                assert await compute_desired_agent_running(uow.session) is False

            # Server enabled
            await server_enable.handle(EnableServerExposureCommand(server_id="srv-1"))
            async with UnitOfWork() as uow:
                assert await compute_desired_agent_running(uow.session) is True

            # Server disabled
            await server_disable.handle(DisableServerExposureCommand(server_id="srv-1"))
            async with UnitOfWork() as uow:
                assert await compute_desired_agent_running(uow.session) is False

            # Panel playit_http enabled
            await panel_handler.handle(
                SetPanelExposureCommand(method="playit_http", desired_state="ENABLED")
            )
            async with UnitOfWork() as uow:
                assert await compute_desired_agent_running(uow.session) is True


class TestPlayitClaimedSecretHandler:
    async def test_handle_playit_claimed_secret_success(self, tmp_path) -> None:
        """Verify _handle_playit_claimed_secret encrypts secret, updates status, and restarts supervisor."""
        proc = _mock_subprocess()
        supervisor = get_playit_supervisor()

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            secret_hex = "d08c824254113c9cccb943435abd2bcb70f54bcb45b56bc8ede3809988d1d88c"
            await _handle_playit_claimed_secret(secret_hex)

            # Check database agent record
            async with UnitOfWork() as uow:
                repo = SQLHostAgentRepository(uow.session)
                agent = await repo.get()
                assert agent.is_claimed is True
                assert agent.process_status == AgentProcessStatus.STARTING

            # Check supervisor is running with decrypted secret file
            assert supervisor.is_running is True
            assert supervisor._secret_file is not None
            assert supervisor._secret_file.exists()
            assert supervisor._secret_file.read_bytes() == secret_hex.encode("utf-8")


class TestPlayitStatusEnumMapping:
    @pytest.mark.parametrize(
        "exposure_status,expected_process_status",
        [
            (ExposureStatus.ACTIVE, AgentProcessStatus.RUNNING),
            (ExposureStatus.DEGRADED, AgentProcessStatus.RUNNING),
            (ExposureStatus.STARTING, AgentProcessStatus.STARTING),
            (ExposureStatus.STOPPING, AgentProcessStatus.STOPPING),
            (ExposureStatus.STOPPED, AgentProcessStatus.STOPPED),
            (ExposureStatus.DISABLED, AgentProcessStatus.STOPPED),
            (ExposureStatus.CLAIM_REQUIRED, AgentProcessStatus.STOPPED),
            (ExposureStatus.ERROR, AgentProcessStatus.ERROR),
            (ExposureStatus.RECLAIM_REQUIRED, AgentProcessStatus.ERROR),
        ],
    )
    async def test_exposure_status_to_process_status_mapping(
        self,
        exposure_status: ExposureStatus,
        expected_process_status: AgentProcessStatus,
    ) -> None:
        assert exposure_status_to_process_status(exposure_status) == expected_process_status
        assert exposure_status_to_process_status(exposure_status.value) == expected_process_status

    async def test_persist_playit_status_does_not_raise_for_active(self, tmp_path) -> None:
        """Regression test for F-04: _persist_playit_status must map ExposureStatus to AgentProcessStatus cleanly."""
        await _seed_claimed_agent(tmp_path)
        await _seed_server("srv-test-enum", "Enum Test", 25565)

        # Calling _persist_playit_status with ExposureStatus.ACTIVE must NOT raise ValueError
        await _persist_playit_status(ExposureStatus.ACTIVE)

        async with UnitOfWork() as uow:
            repo = SQLHostAgentRepository(uow.session)
            agent = await repo.get()
            assert agent.process_status == AgentProcessStatus.RUNNING


class TestPlayitRealTunnelProvisioning:
    async def test_panel_playit_match_existing_tunnel(self, tmp_path) -> None:
        """Idempotency list-first: adopt existing tunnel on port 8000 instead of creating duplicate."""
        await _seed_claimed_agent(tmp_path)
        event_bus = EventBus()
        handler = SetPanelExposureHandler(event_bus)
        proc = _mock_subprocess()

        mock_rundata = PlayitRundataDto(
            agent_id="agent-123",
            agent_type="self-managed",
            account_status="ready",
            tunnels=[
                PlayitTunnelDto(
                    id="tun-panel-existing",
                    name="onx-panel-existing",
                    display_address="existing-panel.at.ply.gg:8000",
                    port_type="tcp",
                    local_ip="127.0.0.1",
                    local_port=8000,
                )
            ],
        )

        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.get_rundata",
                AsyncMock(return_value=mock_rundata),
            ),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.create_tunnel"
            ) as mock_create,
        ):
            res = await handler.handle(
                SetPanelExposureCommand(method="playit_http", desired_state="ENABLED")
            )
            assert res.success is True
            assert res.data["status"] == "ACTIVE"
            assert res.data["playit_tunnel_id"] == "tun-panel-existing"
            assert res.data["public_address"] == "http://existing-panel.at.ply.gg:8000"
            assert res.data["protocol"] == "http"
            assert (
                "Playit.gg free tier exposes the panel over raw TCP (HTTP)"
                in res.data["security_advisory"]
            )
            # create_tunnel should NOT have been called
            mock_create.assert_not_called()

    async def test_panel_playit_create_tunnel_when_not_found(self, tmp_path) -> None:
        """Auto-create tunnel on playit.gg when no matching tunnel exists."""
        await _seed_claimed_agent(tmp_path)
        event_bus = EventBus()
        handler = SetPanelExposureHandler(event_bus)
        proc = _mock_subprocess()

        mock_rundata = PlayitRundataDto(
            agent_id="agent-123",
            agent_type="self-managed",
            account_status="ready",
            tunnels=[],
        )
        mock_new_tunnel = PlayitTunnelDto(
            id="tun-new-created",
            name="onx-panel-new",
            display_address="new-panel.at.ply.gg:12345",
            port_type="tcp",
            local_ip="127.0.0.1",
            local_port=8000,
        )

        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.get_rundata",
                AsyncMock(return_value=mock_rundata),
            ),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.create_tunnel",
                AsyncMock(return_value=mock_new_tunnel),
            ) as mock_create,
        ):
            res = await handler.handle(
                SetPanelExposureCommand(method="playit_http", desired_state="ENABLED")
            )
            assert res.success is True
            assert res.data["status"] == "ACTIVE"
            assert res.data["playit_tunnel_id"] == "tun-new-created"
            assert res.data["public_address"] == "http://new-panel.at.ply.gg:12345"
            mock_create.assert_awaited_once()

    async def test_panel_playit_allocation_full_fallback(self, tmp_path) -> None:
        """Allocation full falls back to STARTING with PLAYIT_ALLOCATION_FULL error code."""
        await _seed_claimed_agent(tmp_path)
        event_bus = EventBus()
        handler = SetPanelExposureHandler(event_bus)
        proc = _mock_subprocess()

        mock_rundata = PlayitRundataDto(
            agent_id="a", agent_type="s", account_status="ready", tunnels=[]
        )

        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.get_rundata",
                AsyncMock(return_value=mock_rundata),
            ),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.create_tunnel",
                AsyncMock(side_effect=PlayitAllocationFullError("Limit reached")),
            ),
        ):
            res = await handler.handle(
                SetPanelExposureCommand(method="playit_http", desired_state="ENABLED")
            )
            assert res.success is True
            assert res.data["status"] == "STARTING"
            assert res.data["error_code"] == "PLAYIT_ALLOCATION_FULL"

    async def test_panel_playit_teardown_deletes_remote_tunnel(self, tmp_path) -> None:
        """Disabling panel playit exposure deletes remote tunnel and clears local credentials."""
        await _seed_claimed_agent(tmp_path)
        event_bus = EventBus()
        handler = SetPanelExposureHandler(event_bus)
        proc = _mock_subprocess()

        mock_new_tunnel = PlayitTunnelDto(
            id="tun-del-123",
            name="onx-panel-del",
            display_address="del-panel.at.ply.gg:8000",
            port_type="tcp",
            local_ip="127.0.0.1",
            local_port=8000,
        )

        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.get_rundata",
                AsyncMock(return_value=PlayitRundataDto("a", "s", "r", [])),
            ),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.create_tunnel",
                AsyncMock(return_value=mock_new_tunnel),
            ),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.delete_tunnel",
                AsyncMock(return_value=True),
            ) as mock_delete,
        ):
            # Enable
            await handler.handle(
                SetPanelExposureCommand(method="playit_http", desired_state="ENABLED")
            )

            # Disable
            res = await handler.handle(
                SetPanelExposureCommand(method="playit_http", desired_state="DISABLED")
            )
            assert res.success is True
            assert res.data["status"] == "DISABLED"
            assert res.data["playit_tunnel_id"] is None
            mock_delete.assert_awaited_once_with(
                "valid-agent-secret",
                "tun-del-123",
            )

    async def test_server_playit_match_or_create_and_delete(self, tmp_path) -> None:
        """Server exposure enables real tunnel provisioning and deletes remote tunnel on disable."""
        await _seed_claimed_agent(tmp_path)
        await _seed_server("srv-mc-1", "MC Server 1", 25565)
        event_bus = EventBus()
        enable_handler = EnableServerExposureHandler(event_bus)
        disable_handler = DisableServerExposureHandler(event_bus)
        proc = _mock_subprocess()

        mock_created_tunnel = PlayitTunnelDto(
            id="tun-srv-mc-1",
            name="onx-srv-mc-java",
            display_address="mc-play.at.ply.gg:25565",
            port_type="tcp",
            local_ip="127.0.0.1",
            local_port=25565,
        )

        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.get_rundata",
                AsyncMock(return_value=PlayitRundataDto("a", "s", "r", [])),
            ),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.create_tunnel",
                AsyncMock(return_value=mock_created_tunnel),
            ) as mock_create,
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.delete_tunnel",
                AsyncMock(return_value=True),
            ) as mock_delete,
        ):
            # Enable
            res = await enable_handler.handle(EnableServerExposureCommand(server_id="srv-mc-1"))
            assert res.success is True
            assert res.data["aggregate_status"] == "ACTIVE"
            assert len(res.data["targets"]) == 1
            assert res.data["targets"][0]["public_address"] == "mc-play.at.ply.gg:25565"
            mock_create.assert_awaited_once()

            # Disable
            res = await disable_handler.handle(DisableServerExposureCommand(server_id="srv-mc-1"))
            assert res.success is True
            assert res.data["aggregate_status"] == "DISABLED"
            mock_delete.assert_awaited_once_with(
                "valid-agent-secret",
                "tun-srv-mc-1",
            )

    async def test_reconcile_playit_tunnels_auto_adoption(self, tmp_path) -> None:
        """Background reconciliation adopts dashboard-created tunnel for pending server target."""
        await _seed_claimed_agent(tmp_path)
        await _seed_server("srv-adopt", "Adoption Test Server", 25565)
        event_bus = EventBus()
        enable_handler = EnableServerExposureHandler(event_bus)
        proc = _mock_subprocess()

        # Step 1: Enable server exposure when creation initially fails (falls back to STARTING / PLAYIT_TUNNEL_CREATION_PENDING)
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.get_rundata",
                AsyncMock(return_value=PlayitRundataDto("a", "s", "r", [])),
            ),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.create_tunnel",
                AsyncMock(side_effect=Exception("API offline")),
            ),
        ):
            res = await enable_handler.handle(EnableServerExposureCommand(server_id="srv-adopt"))
            assert res.success is True
            assert res.data["aggregate_status"] == "STARTING"
            assert res.data["targets"][0]["status"] == "STARTING"
            assert res.data["targets"][0]["error_code"] == "PLAYIT_TUNNEL_CREATION_PENDING"

        # Step 2: User creates tunnel manually on playit dashboard -> next reconciliation run adopts it
        mock_discovered_rundata = PlayitRundataDto(
            agent_id="a",
            agent_type="s",
            account_status="ready",
            tunnels=[
                PlayitTunnelDto(
                    id="tun-discovered-99",
                    name="custom-dash-tunnel",
                    display_address="dash-play.at.ply.gg:25565",
                    port_type="tcp",
                    local_ip="127.0.0.1",
                    local_port=25565,
                )
            ],
        )

        with patch(
            "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.get_rundata",
            AsyncMock(return_value=mock_discovered_rundata),
        ):
            await _reconcile_playit_tunnels()

            async with UnitOfWork() as uow:
                repo = SQLServerExposureRepository(uow.session)
                exp = await repo.get("srv-adopt")
                assert exp is not None
                assert exp.aggregate_status == ExposureStatus.ACTIVE
                assert exp.targets[0].status == ExposureStatus.ACTIVE
                assert exp.targets[0].playit_tunnel_id == "tun-discovered-99"
                assert exp.targets[0].public_address == "dash-play.at.ply.gg:25565"
