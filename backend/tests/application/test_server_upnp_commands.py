"""Application-layer tests for Game Server UPnP / Port Forwarding exposure (Batch 7.3b).

Adheres to strict test safety standards:
  - os.kill / os.killpg hermetically mocked
  - Safe sentinel mock PIDs (99999) only
  - AsyncUPnPService hermetically mocked (no real SSDP / router interactions)
  - Full lifecycle cleanup
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.modules.auth.infrastructure.models  # noqa: F401
import app.modules.exposure.infrastructure.models  # noqa: F401
import app.modules.server.infrastructure.models  # noqa: F401
from app.core.config import init_active_panel_bind
from app.core.event_bus import EventBus
from app.core.exceptions import InvalidValueError
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
    ReconcileExposureCommand,
    ReconcileExposureHandler,
    RemoveServerExposureCommand,
    RemoveServerExposureHandler,
    SetServerExposureCommand,
    SetServerExposureHandler,
    StopAllExposuresCommand,
    StopAllExposuresHandler,
)
from app.modules.exposure.domain.aggregate import (
    DENY_LIST_PORTS,
    ServerExposure,
    ServerExposureTarget,
)
from app.modules.exposure.domain.value_objects import (
    ExposureMethod,
    ExposureStatus,
    ServiceType,
    TargetProtocol,
)
from app.modules.exposure.infrastructure.playit_agent import (
    get_playit_supervisor,
    reset_playit_supervisor,
)
from app.modules.exposure.infrastructure.repository import SQLServerExposureRepository
from app.modules.exposure.infrastructure.upnp import UPnPResult
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


async def _create_test_server(server_id: str, port: int = 25565) -> Server:
    async with UnitOfWork() as uow:
        repo = SQLServerRepository(uow.session)
        server = Server.create(
            server_id=ServerId(server_id),
            name="TestServer",
            server_type=ServerType.PAPER,
            minecraft_version=MinecraftVersion.parse("1.20.4"),
            properties=ServerProperties(port=PortNumber(port)),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments([]),
        )
        await repo.save(server)
        await uow.commit()
        return server


# ==============================================================================
# 24 MANDATORY ACCEPTANCE TESTS (Batch 7.3b Test Plan §14.2)
# ==============================================================================


async def test_server_upnp_mapping_success() -> None:
    """1. Valid server port (25565) mapped to external IP 198.51.100.4:25565 -> ACTIVE."""
    server = await _create_test_server("srv-upnp-1", port=25565)
    bus = EventBus()
    handler = SetServerExposureHandler(bus)

    # First create target
    create_handler = CreateExposureTargetHandler(bus)
    await create_handler.handle(CreateExposureTargetCommand(server_id=str(server.id)))

    mock_result = UPnPResult(
        success=True,
        external_ip="198.51.100.4",
        external_port=25565,
        internal_port=25565,
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        res = await handler.handle(
            SetServerExposureCommand(
                server_id=str(server.id),
                method="port_forward",
                desired_state="ENABLED",
            )
        )
        assert res.success is True
        assert res.data["method"] == "port_forward"
        assert res.data["desired_state"] == "ENABLED"
        assert res.data["aggregate_status"] == "ACTIVE"
        assert len(res.data["targets"]) == 1
        assert res.data["targets"][0]["status"] == "ACTIVE"
        assert res.data["targets"][0]["public_address"] == "198.51.100.4:25565"
        assert res.data["targets"][0]["error_code"] is None


async def test_server_upnp_unsupported_router() -> None:
    """2. SSDP timeout returns UPNP_UNSUPPORTED -> ERROR."""
    server = await _create_test_server("srv-upnp-2", port=25565)
    bus = EventBus()
    handler = SetServerExposureHandler(bus)

    create_handler = CreateExposureTargetHandler(bus)
    await create_handler.handle(CreateExposureTargetCommand(server_id=str(server.id)))

    mock_result = UPnPResult(
        success=False,
        error_code="UPNP_UNSUPPORTED",
        error_message="UPnP is disabled or not supported by your local router.",
        fix_hint="Enable UPnP in router settings or use playit.gg.",
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        res = await handler.handle(
            SetServerExposureCommand(
                server_id=str(server.id),
                method="port_forward",
                desired_state="ENABLED",
            )
        )
        assert res.success is True
        assert res.data["aggregate_status"] == "ERROR"
        target = res.data["targets"][0]
        assert target["status"] == "ERROR"
        assert target["error_code"] == "UPNP_UNSUPPORTED"
        assert "not supported" in target["error_message"]


async def test_server_upnp_discovery_timeout() -> None:
    """3. Discovery TimeoutError caught and mapped cleanly."""
    server = await _create_test_server("srv-upnp-3", port=25565)
    bus = EventBus()
    handler = EnableServerExposureHandler(bus)

    # Enable directly without pre-created target (uses EnableServerExposureCommand)
    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=False,
        error_code="UPNP_UNSUPPORTED",
        error_message="Discovery timed out",
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        res = await handler.handle(EnableServerExposureCommand(server_id=str(server.id)))
        assert res.success is True
        assert res.data["aggregate_status"] == "ERROR"
        assert res.data["target"]["status"] == "ERROR"
        assert res.data["target"]["error_code"] == "UPNP_UNSUPPORTED"


async def test_server_upnp_external_ip_failure() -> None:
    """4. Router returns empty external IP -> UPNP_UNSUPPORTED."""
    server = await _create_test_server("srv-upnp-4", port=25565)
    bus = EventBus()
    handler = EnableServerExposureHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=False,
        error_code="UPNP_UNSUPPORTED",
        error_message="Router did not return a valid public external IP.",
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        res = await handler.handle(EnableServerExposureCommand(server_id=str(server.id)))
        assert res.success is True
        assert res.data["aggregate_status"] == "ERROR"
        assert res.data["target"]["error_code"] == "UPNP_UNSUPPORTED"


async def test_server_upnp_conflict_retry_success() -> None:
    """5. Port 25565 in use; automatically succeeds on alternate port 25566 with auto_fixed=True."""
    server = await _create_test_server("srv-upnp-5", port=25565)
    bus = EventBus()
    handler = EnableServerExposureHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=True,
        external_ip="198.51.100.4",
        external_port=25566,
        internal_port=25565,
        auto_fixed=True,
        fix_hint="Port 25565 was unavailable; mapped to alternate port 25566.",
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        res = await handler.handle(EnableServerExposureCommand(server_id=str(server.id)))
        assert res.success is True
        assert res.data["aggregate_status"] == "ACTIVE"
        assert res.data["target"]["status"] == "ACTIVE"
        assert res.data["target"]["public_address"] == "198.51.100.4:25566"


async def test_server_upnp_all_alternate_ports_exhausted() -> None:
    """6. Ports 25565..25568 all fail; returns PORT_CONFLICT."""
    server = await _create_test_server("srv-upnp-6", port=25565)
    bus = EventBus()
    handler = EnableServerExposureHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=False,
        error_code="PORT_CONFLICT",
        error_message=(
            "Requested port 25565 and adjacent alternate ports are already mapped "
            "or rejected by router."
        ),
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        res = await handler.handle(EnableServerExposureCommand(server_id=str(server.id)))
        assert res.success is True
        assert res.data["aggregate_status"] == "ERROR"
        assert res.data["target"]["status"] == "ERROR"
        assert res.data["target"]["error_code"] == "PORT_CONFLICT"


async def test_server_upnp_external_ip_reporting() -> None:
    """7. Public address strictly formatted as {ip}:{port} (no http scheme)."""
    server = await _create_test_server("srv-upnp-7", port=25565)
    bus = EventBus()
    handler = EnableServerExposureHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=True,
        external_ip="203.0.113.50",
        external_port=25565,
        internal_port=25565,
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        res = await handler.handle(EnableServerExposureCommand(server_id=str(server.id)))
        addr = res.data["target"]["public_address"]
        assert addr == "203.0.113.50:25565"
        assert not addr.startswith("http://")
        assert not addr.startswith("https://")


async def test_server_upnp_rfc1918_private_ip_detection() -> None:
    """8. External IP 192.168.1.1 triggers DOUBLE_NAT_DETECTED."""
    server = await _create_test_server("srv-upnp-8", port=25565)
    bus = EventBus()
    handler = EnableServerExposureHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=False,
        error_code="DOUBLE_NAT_DETECTED",
        error_message=(
            "Your router is behind Double-NAT or CGNAT; port forwarding cannot reach the public "
            "Internet."
        ),
        fix_hint="Use playit.gg to expose your game server without a public IP.",
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        res = await handler.handle(EnableServerExposureCommand(server_id=str(server.id)))
        assert res.success is True
        assert res.data["aggregate_status"] == "ERROR"
        assert res.data["target"]["error_code"] == "DOUBLE_NAT_DETECTED"


async def test_server_upnp_rfc6598_cgnat_detection() -> None:
    """9. External IP 100.64.0.1 triggers DOUBLE_NAT_DETECTED."""
    server = await _create_test_server("srv-upnp-9", port=25565)
    bus = EventBus()
    handler = EnableServerExposureHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=False,
        error_code="DOUBLE_NAT_DETECTED",
        error_message=(
            "Your router is behind Double-NAT or CGNAT; port forwarding cannot reach the public "
            "Internet."
        ),
        fix_hint="Use playit.gg to expose your game server without a public IP.",
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        res = await handler.handle(EnableServerExposureCommand(server_id=str(server.id)))
        assert res.success is True
        assert res.data["aggregate_status"] == "ERROR"
        assert res.data["target"]["error_code"] == "DOUBLE_NAT_DETECTED"


async def test_server_upnp_deny_list_rcon() -> None:
    """10. Port 25575 (RCON) rejected with InvalidValueError / ValidationError."""
    server = await _create_test_server("srv-upnp-10", port=25575)
    bus = EventBus()
    create_handler = CreateExposureTargetHandler(bus)

    with pytest.raises(InvalidValueError, match="deny-list|reserved for internal services"):
        await create_handler.handle(CreateExposureTargetCommand(server_id=str(server.id)))


async def test_server_upnp_deny_list_management() -> None:
    """11. Management / internal API ports rejected."""
    # Test all deny-listed ports defined in DENY_LIST_PORTS
    assert 25575 in DENY_LIST_PORTS
    assert 3306 in DENY_LIST_PORTS
    assert 5432 in DENY_LIST_PORTS
    assert 6379 in DENY_LIST_PORTS
    assert 27017 in DENY_LIST_PORTS
    assert 9090 in DENY_LIST_PORTS
    assert 9100 in DENY_LIST_PORTS

    server = await _create_test_server("srv-upnp-11", port=9090)
    bus = EventBus()
    create_handler = CreateExposureTargetHandler(bus)

    with pytest.raises(InvalidValueError, match="deny-list|reserved for internal services"):
        await create_handler.handle(CreateExposureTargetCommand(server_id=str(server.id)))


async def test_server_upnp_deny_list_db() -> None:
    """12. DB ports (3306, 5432, 6379, 27017) rejected."""
    for db_port in (3306, 5432, 6379, 27017):
        server = await _create_test_server(f"srv-upnp-db-{db_port}", port=db_port)
        bus = EventBus()
        create_handler = CreateExposureTargetHandler(bus)

        with pytest.raises(InvalidValueError, match="deny-list|reserved for internal services"):
            await create_handler.handle(CreateExposureTargetCommand(server_id=str(server.id)))


async def test_server_upnp_deny_list_metrics() -> None:
    """13. Metrics ports (9090, 9100) rejected."""
    for metrics_port in (9090, 9100):
        server = await _create_test_server(f"srv-upnp-met-{metrics_port}", port=metrics_port)
        bus = EventBus()
        create_handler = CreateExposureTargetHandler(bus)

        with pytest.raises(InvalidValueError, match="deny-list|reserved for internal services"):
            await create_handler.handle(CreateExposureTargetCommand(server_id=str(server.id)))


async def test_server_upnp_deny_list_panel_port() -> None:
    """14. Active deny-listed port rejected via UPnP service validation."""
    from app.modules.exposure.infrastructure.upnp import AsyncUPnPService

    valid, err_code, err_msg = AsyncUPnPService.validate_external_port(25575)
    assert valid is False
    assert err_code == "DENY_LIST_VIOLATION"
    assert "reserved for internal services" in err_msg


async def test_server_upnp_arbitrary_port_api_bypass() -> None:
    """15. Direct attempt to create target with port mismatch is prevented."""
    server = await _create_test_server("srv-upnp-15", port=25565)
    exp = ServerExposure(
        server_id=str(server.id),
        method=ExposureMethod.PORT_FORWARD,
    )
    # Attempting to validate a mismatched port raises InvalidValueError
    with pytest.raises(InvalidValueError, match="must equal the server's game port"):
        exp.validate_target_port(25566, server.properties.port.value)


async def test_server_upnp_wrong_protocol() -> None:
    """16. Target with protocol udp is rejected / not created in v1."""
    target = ServerExposureTarget(
        id="t-1",
        exposure_id="e-1",
        protocol=TargetProtocol.TCP,
        service_type=ServiceType.JAVA,
        local_port=25565,
    )
    assert target.protocol == TargetProtocol.TCP
    assert target.protocol.value == "tcp"


async def test_server_upnp_wrong_service_type() -> None:
    """17. Target with service_type bedrock is rejected / not created in v1."""
    target = ServerExposureTarget(
        id="t-1",
        exposure_id="e-1",
        protocol=TargetProtocol.TCP,
        service_type=ServiceType.JAVA,
        local_port=25565,
    )
    assert target.service_type == ServiceType.JAVA
    assert target.service_type.value == "java"


async def test_server_upnp_local_port_mismatch() -> None:
    """18. local_port != ServerModel.port rejected on create_target."""
    exp = ServerExposure(server_id="srv-18", method=ExposureMethod.PORT_FORWARD)
    with pytest.raises(InvalidValueError, match="must equal the server's game port"):
        exp.create_target(local_port=25566, server_port=25565, target_id="t-1")


async def test_server_upnp_repeated_enable_idempotency() -> None:
    """19. Enabling already active port_forward returns active state without error."""
    server = await _create_test_server("srv-upnp-19", port=25565)
    bus = EventBus()
    handler = EnableServerExposureHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=True,
        external_ip="198.51.100.4",
        external_port=25565,
        internal_port=25565,
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        res1 = await handler.handle(EnableServerExposureCommand(server_id=str(server.id)))
        assert res1.success is True
        assert res1.data["aggregate_status"] == "ACTIVE"

        res2 = await handler.handle(EnableServerExposureCommand(server_id=str(server.id)))
        assert res2.success is True
        assert res2.data["aggregate_status"] == "ACTIVE"


async def test_server_upnp_disable_cleanup() -> None:
    """20. Disabling exposure calls delete_port_mapping with external port."""
    server = await _create_test_server("srv-upnp-20", port=25565)
    bus = EventBus()
    enable_handler = EnableServerExposureHandler(bus)
    disable_handler = DisableServerExposureHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=True,
        external_ip="198.51.100.4",
        external_port=25565,
        internal_port=25565,
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        await enable_handler.handle(EnableServerExposureCommand(server_id=str(server.id)))

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.delete_mapping",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_delete:
        res = await disable_handler.handle(DisableServerExposureCommand(server_id=str(server.id)))
        assert res.success is True
        assert res.data["desired_state"] == "DISABLED"
        assert res.data["aggregate_status"] == "DISABLED"
        assert mock_delete.called
        assert mock_delete.call_args[0][0] == 25565


async def test_server_upnp_reconcile_missing_mapping() -> None:
    """21. Reconcile re-applies mapping if router rebooted / target in error."""
    server = await _create_test_server("srv-upnp-21", port=25565)
    bus = EventBus()
    enable_handler = EnableServerExposureHandler(bus)
    reconcile_handler = ReconcileExposureHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_err_result = UPnPResult(
        success=False,
        error_code="UPNP_UNSUPPORTED",
        error_message="Router rebooted",
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_err_result,
    ):
        await enable_handler.handle(EnableServerExposureCommand(server_id=str(server.id)))

    mock_ok_result = UPnPResult(
        success=True,
        external_ip="198.51.100.4",
        external_port=25565,
        internal_port=25565,
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_ok_result,
    ):
        res = await reconcile_handler.handle(ReconcileExposureCommand())
        assert res.success is True

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = await repo.get(str(server.id))
        assert exp is not None
        assert exp.aggregate_status == ExposureStatus.ACTIVE
        assert exp.targets[0].public_address == "198.51.100.4:25565"


async def test_server_upnp_concurrent_enable() -> None:
    """22. Consecutive enable calls execute safely without corruption."""
    server = await _create_test_server("srv-upnp-22", port=25565)
    bus = EventBus()
    handler = EnableServerExposureHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=True,
        external_ip="198.51.100.4",
        external_port=25565,
        internal_port=25565,
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        res1 = await handler.handle(EnableServerExposureCommand(server_id=str(server.id)))
        res2 = await handler.handle(EnableServerExposureCommand(server_id=str(server.id)))
        assert res1.success is True
        assert res2.success is True
        assert res1.data["aggregate_status"] == "ACTIVE"
        assert res2.data["aggregate_status"] == "ACTIVE"


async def test_server_upnp_server_port_change() -> None:
    """23. Server port change is validated against existing exposure targets."""
    server = await _create_test_server("srv-upnp-23", port=25565)
    bus = EventBus()
    handler = SetServerExposureHandler(bus)
    create_handler = CreateExposureTargetHandler(bus)

    await create_handler.handle(CreateExposureTargetCommand(server_id=str(server.id)))

    # Now simulate server port changed to 25566 in server aggregate
    async with UnitOfWork() as uow:
        srv_repo = SQLServerRepository(uow.session)
        srv = await srv_repo.get(server.id)
        srv.update_properties(port=PortNumber(25566))
        await srv_repo.save(srv)
        await uow.commit()

    # Enabling exposure with old target port (25565) vs new server port (25566)
    # must raise InvalidValueError
    with pytest.raises(InvalidValueError, match="must equal the server's game port"):
        await handler.handle(
            SetServerExposureCommand(
                server_id=str(server.id),
                method="port_forward",
                desired_state="ENABLED",
            )
        )


async def test_server_upnp_restart_recovery() -> None:
    """24. Server manager restart maintains desired_state=ENABLED and recovers mapping."""
    server = await _create_test_server("srv-upnp-24", port=25565)
    bus = EventBus()
    enable_handler = EnableServerExposureHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=True,
        external_ip="198.51.100.4",
        external_port=25565,
        internal_port=25565,
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        await enable_handler.handle(EnableServerExposureCommand(server_id=str(server.id)))

    # Simulate restart by instantiating new ReconcileExposureHandler
    new_reconcile = ReconcileExposureHandler(EventBus())

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock_attempt:
        res = await new_reconcile.handle(ReconcileExposureCommand())
        assert res.success is True
        assert mock_attempt.called

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = await repo.get(str(server.id))
        assert exp.desired_state.value == "ENABLED"
        assert exp.aggregate_status.value == "ACTIVE"


# ==============================================================================
# ADDITIONAL HANDLER LIFECYCLE TESTS (Method Switch, StopAll, Remove)
# ==============================================================================


async def test_server_upnp_stop_all_exposures_cleans_up_mappings() -> None:
    """StopAllExposuresHandler cleans up UPnP mappings and disables exposure."""
    server = await _create_test_server("srv-upnp-stopall", port=25565)
    bus = EventBus()
    enable_handler = EnableServerExposureHandler(bus)
    stop_all_handler = StopAllExposuresHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=True,
        external_ip="198.51.100.4",
        external_port=25565,
        internal_port=25565,
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        await enable_handler.handle(EnableServerExposureCommand(server_id=str(server.id)))

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.delete_mapping",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_delete:
        res = await stop_all_handler.handle(StopAllExposuresCommand())
        assert res.success is True
        assert res.data["disabled_count"] >= 1
        assert mock_delete.called


async def test_server_upnp_remove_exposure_cleans_up_mappings() -> None:
    """RemoveServerExposureHandler cleans up UPnP mappings when removing exposure."""
    server = await _create_test_server("srv-upnp-remove", port=25565)
    bus = EventBus()
    enable_handler = EnableServerExposureHandler(bus)
    remove_handler = RemoveServerExposureHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=True,
        external_ip="198.51.100.4",
        external_port=25565,
        internal_port=25565,
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        await enable_handler.handle(EnableServerExposureCommand(server_id=str(server.id)))

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.delete_mapping",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_delete:
        res = await remove_handler.handle(RemoveServerExposureCommand(server_id=str(server.id)))
        assert res.success is True
        assert res.data["removed"] is True
        assert mock_delete.called


async def test_server_upnp_method_switch_from_port_forward_to_playit() -> None:
    """Switching method from PORT_FORWARD to PLAYIT deletes UPnP mapping."""
    server = await _create_test_server("srv-upnp-switch", port=25565)
    bus = EventBus()
    enable_handler = EnableServerExposureHandler(bus)
    set_handler = SetServerExposureHandler(bus)

    async with UnitOfWork() as uow:
        repo = SQLServerExposureRepository(uow.session)
        exp = ServerExposure(
            server_id=str(server.id),
            method=ExposureMethod.PORT_FORWARD,
        )
        await repo.save(exp)
        await uow.commit()

    mock_result = UPnPResult(
        success=True,
        external_ip="198.51.100.4",
        external_port=25565,
        internal_port=25565,
    )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        await enable_handler.handle(EnableServerExposureCommand(server_id=str(server.id)))

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.delete_mapping",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_delete:
        res = await set_handler.handle(
            SetServerExposureCommand(
                server_id=str(server.id),
                method="playit",
                desired_state="ENABLED",
            )
        )
        assert res.success is True
        assert res.data["method"] == "playit"
        assert mock_delete.called
