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
    compute_desired_agent_running,
)
from app.modules.exposure.domain.value_objects import ExposureStatus
from app.modules.exposure.infrastructure.playit_agent import (
    PlayitAgentSupervisor,
    get_playit_supervisor,
    reset_playit_supervisor,
)
from app.modules.exposure.infrastructure.repository import SQLHostAgentRepository
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
        patch("os.killpg") as mock_killpg,
        patch("os.getpgid", return_value=SAFE_SENTINEL_PID),
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
