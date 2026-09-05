"""Application-layer tests for Bedrock/UDP Targets & Companion-Service Ports (Batch 7.3d).

Adheres to strict test safety standards:
  - os.kill / os.killpg hermetically mocked
  - Safe sentinel mock PIDs (99999) only
  - Zero real subprocess spawning
  - Zero real UPnP or Cloudflare network calls
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.modules.auth.infrastructure.models  # noqa: F401
import app.modules.exposure.infrastructure.models  # noqa: F401
import app.modules.server.infrastructure.models  # noqa: F401
from app.core.config import init_active_panel_bind
from app.core.event_bus import EventBus
from app.core.exceptions import InvalidValueError, NotFoundError
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.settings_store import init_settings_store
from app.modules.exposure.application import commands as exposure_commands
from app.modules.exposure.application.commands import (
    CreateExposureTargetCommand,
    CreateExposureTargetHandler,
    DeleteServerPortCommand,
    DeleteServerPortHandler,
    DisableServerExposureCommand,
    DisableServerExposureHandler,
    EnableServerExposureCommand,
    EnableServerExposureHandler,
    RegisterServerPortCommand,
    RegisterServerPortHandler,
    SetServerExposureCommand,
    SetServerExposureHandler,
    StopAllExposuresCommand,
    StopAllExposuresHandler,
)
from app.modules.exposure.application.queries import (
    GetServerExposureHandler,
    GetServerExposureQuery,
    ListExposureTargetsHandler,
    ListExposureTargetsQuery,
    ListServerPortsHandler,
    ListServerPortsQuery,
)
from app.modules.exposure.domain.exceptions import (
    DuplicateTargetError,
    InvalidServiceTypeError,
    MethodProtocolIncompatibleError,
    PortAlreadyRegisteredError,
    UnregisteredPortError,
)
from app.modules.exposure.domain.value_objects import (
    ExposureMethod,
    ExposureStatus,
)
from app.modules.exposure.infrastructure.cloudflare import TunnelProvisionResult
from app.modules.exposure.infrastructure.cloudflared import reset_server_cloudflared_supervisors
from app.modules.exposure.infrastructure.playit_agent import (
    get_playit_supervisor,
    reset_playit_supervisor,
)
from app.modules.exposure.infrastructure.repository import (
    SQLHostAgentRepository,
)
from app.modules.exposure.infrastructure.upnp import UPnPResult
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
)
from app.modules.server.domain.value_objects import (
    ServerType as ServerDomainType,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import MinecraftVersion, ServerId

pytestmark = pytest.mark.asyncio

SAFE_SENTINEL_PID = 99999
_HOSTNAME = "play.example.com"
_API_TOKEN = "cf-api-token-srv-multi-target"
_TUNNEL_TOKEN = "provisioned-srv-tunnel-token-xyz"


class FakeCloudflareClient:
    def __init__(self) -> None:
        self.ingresses: list[tuple[str, list[dict[str, str]]]] = []
        self.cnames: list[tuple[str, str]] = []

    async def create_named_tunnel(self, name: str) -> TunnelProvisionResult:
        _ = name
        return TunnelProvisionResult(tunnel_id="tun-srv-multi", token=_TUNNEL_TOKEN)

    async def configure_ingress(self, tunnel_id: str, ingress: list[dict[str, str]]) -> None:
        self.ingresses.append((tunnel_id, ingress))

    async def create_cname(self, hostname: str, tunnel_id: str) -> str:
        self.cnames.append((hostname, tunnel_id))
        return "dns-srv-multi"


class FakeServerSupervisor:
    def __init__(self, server_id: str = "srv-1") -> None:
        self.server_id = server_id
        self.stops = 0
        self.starts: list[bytes] = []
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self, token: bytes, *, _on_status=None) -> None:
        self.starts.append(token)
        self._running = True

    async def stop(self) -> None:
        self.stops += 1
        self._running = False


class FakeUPnPService:
    def __init__(self) -> None:
        self.attempts: list[dict] = []
        self.deletions: list[dict] = []

    async def attempt_mapping(
        self,
        internal_port: int,
        requested_external_port: int,
        description: str,
        protocol: str = "TCP",
    ) -> UPnPResult:
        self.attempts.append(
            {
                "internal_port": internal_port,
                "requested_external_port": requested_external_port,
                "description": description,
                "protocol": protocol,
            }
        )
        return UPnPResult(
            success=True,
            external_ip="198.51.100.1",
            external_port=requested_external_port,
        )

    async def delete_mapping(self, port: int, protocol: str = "TCP") -> None:
        self.deletions.append({"port": port, "protocol": protocol})


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

    key_path = str(tmp_path / "backup_key.bin")
    monkeypatch.setenv("MCS_BACKUP_ENCRYPTION_KEY_PATH", key_path)

    await get_playit_supervisor().stop()
    reset_playit_supervisor()
    reset_server_cloudflared_supervisors()

    yield

    await get_playit_supervisor().stop()
    reset_playit_supervisor()
    reset_server_cloudflared_supervisors()
    await engine.dispose()
    database._engine = None
    database._session_factory = None


async def _create_test_server(server_id_str: str = "srv-1", port: int = 25565) -> Server:
    async with database._session_factory() as session:
        repo = SQLServerRepository(session)
        server = Server.create(
            server_id=ServerId(server_id_str),
            name="Survival World",
            server_type=ServerDomainType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.20.4"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments([]),
            properties=ServerProperties(port=PortNumber(port)),
        )
        await repo.save(server)
        await session.commit()
        return server


async def _seed_claimed_agent() -> None:
    from app.modules.exposure.application.commands import _panel_encryption

    ciphertext = _panel_encryption().encrypt(b"valid-agent-secret")
    async with database._session_factory() as session:
        repo = SQLHostAgentRepository(session)
        agent = await repo.get()
        agent.store_secret(ciphertext)
        await repo.save(agent)
        await session.commit()


# ===========================================================================
# 24 Acceptance Tests (Section 10 of Design Spec)
# ===========================================================================


async def test_register_companion_port_success():
    """Test 1: Valid companion port registration (Bedrock UDP 19132) persists correctly."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    handler = RegisterServerPortHandler(bus)

    result = await handler.handle(
        RegisterServerPortCommand(
            server_id="srv-1",
            service_type="bedrock",
            protocol="udp",
            port=19132,
            name="Bedrock Edition",
        )
    )

    assert result.success is True
    data = result.data
    assert data["server_id"] == "srv-1"
    assert data["service_type"] == "bedrock"
    assert data["protocol"] == "udp"
    assert data["port"] == 19132
    assert data["name"] == "Bedrock Edition"

    # Query verify
    query_handler = ListServerPortsHandler()
    ports = await query_handler.handle(ListServerPortsQuery(server_id="srv-1"))
    assert len(ports) == 1
    assert ports[0]["service_type"] == "bedrock"
    assert ports[0]["port"] == 19132


async def test_register_companion_port_java_rejected():
    """Test 2: Attempt to register service_type='java' in server_registered_ports is rejected."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    handler = RegisterServerPortHandler(bus)

    with pytest.raises(InvalidServiceTypeError):
        await handler.handle(
            RegisterServerPortCommand(
                server_id="srv-1",
                service_type="java",
                protocol="tcp",
                port=25565,
            )
        )


async def test_register_companion_port_deny_list_rejected():
    """Test 3: Registering a deny-listed port (e.g. 25575 RCON) is rejected."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    handler = RegisterServerPortHandler(bus)

    with pytest.raises(InvalidValueError) as exc:
        await handler.handle(
            RegisterServerPortCommand(
                server_id="srv-1",
                service_type="voice",
                protocol="udp",
                port=25575,
            )
        )
    assert exc.value.details["field"] == "port"


async def test_register_companion_port_duplicate_type_rejected():
    """Test 4: Registering a duplicate service type on the same server returns 409."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    handler = RegisterServerPortHandler(bus)

    await handler.handle(
        RegisterServerPortCommand(
            server_id="srv-1",
            service_type="bedrock",
            protocol="udp",
            port=19132,
        )
    )

    with pytest.raises(PortAlreadyRegisteredError):
        await handler.handle(
            RegisterServerPortCommand(
                server_id="srv-1",
                service_type="bedrock",
                protocol="udp",
                port=19133,
            )
        )


async def test_register_companion_port_duplicate_port_protocol_rejected():
    """Test 5: Registering the same port/protocol twice on the same server returns 409."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    handler = RegisterServerPortHandler(bus)

    await handler.handle(
        RegisterServerPortCommand(
            server_id="srv-1",
            service_type="bedrock",
            protocol="udp",
            port=24454,
        )
    )

    with pytest.raises(PortAlreadyRegisteredError):
        await handler.handle(
            RegisterServerPortCommand(
                server_id="srv-1",
                service_type="voice",
                protocol="udp",
                port=24454,
            )
        )


async def test_create_bedrock_udp_target_success():
    """Test 6: Creating a Bedrock UDP target with registered port succeeds."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1",
            service_type="bedrock",
            protocol="udp",
            port=19132,
        )
    )

    target_res = await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(
            server_id="srv-1",
            service_type="bedrock",
            protocol="udp",
            local_port=19132,
        )
    )

    assert target_res.success is True
    assert target_res.data["service_type"] == "bedrock"
    assert target_res.data["protocol"] == "udp"
    assert target_res.data["local_port"] == 19132


async def test_create_bedrock_udp_target_unregistered_rejected():
    """Test 7: Creating a Bedrock target without registering the port first is rejected (422)."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()

    with pytest.raises(UnregisteredPortError):
        await CreateExposureTargetHandler(bus).handle(
            CreateExposureTargetCommand(
                server_id="srv-1",
                service_type="bedrock",
                protocol="udp",
                local_port=19132,
            )
        )


async def test_create_voice_chat_udp_target_success():
    """Test 8: Creating a Simple Voice Chat UDP target succeeds with registered port."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1",
            service_type="voice",
            protocol="udp",
            port=24454,
        )
    )

    res = await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(
            server_id="srv-1",
            service_type="voice",
            protocol="udp",
        )
    )
    assert res.success is True
    assert res.data["service_type"] == "voice"
    assert res.data["protocol"] == "udp"
    assert res.data["local_port"] == 24454


async def test_create_bluemap_tcp_target_success():
    """Test 9: Creating a BlueMap TCP target succeeds with registered port."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1",
            service_type="bluemap",
            protocol="tcp",
            port=8100,
        )
    )

    res = await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(
            server_id="srv-1",
            service_type="bluemap",
            protocol="tcp",
        )
    )
    assert res.success is True
    assert res.data["service_type"] == "bluemap"
    assert res.data["protocol"] == "tcp"
    assert res.data["local_port"] == 8100


async def test_create_target_wrong_protocol_rejected():
    """Test 10: Creating Bedrock with TCP or BlueMap with UDP is rejected (422)."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1",
            service_type="bedrock",
            protocol="udp",
            port=19132,
        )
    )

    with pytest.raises(InvalidValueError) as exc:
        await CreateExposureTargetHandler(bus).handle(
            CreateExposureTargetCommand(
                server_id="srv-1",
                service_type="bedrock",
                protocol="tcp",
            )
        )
    assert exc.value.details["field"] == "protocol"


async def test_multi_target_coexistence_same_server():
    """Test 11: Server with Java TCP + Bedrock UDP + Voice UDP targets exposes all 3."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()

    # Register ports
    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1", service_type="bedrock", protocol="udp", port=19132
        )
    )
    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1", service_type="voice", protocol="udp", port=24454
        )
    )

    # Create 3 targets: Java (default), Bedrock, Voice
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="java")
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="bedrock")
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="voice")
    )

    targets = await ListExposureTargetsHandler().handle(ListExposureTargetsQuery(server_id="srv-1"))
    assert len(targets) == 3
    types = {t["service_type"] for t in targets}
    assert types == {"java", "bedrock", "voice"}


async def test_multi_target_duplicate_service_rejected():
    """Test 12: Creating a second Bedrock target on a server that already has one returns 409."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1", service_type="bedrock", protocol="udp", port=19132
        )
    )

    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="bedrock")
    )

    with pytest.raises(DuplicateTargetError):
        await CreateExposureTargetHandler(bus).handle(
            CreateExposureTargetCommand(server_id="srv-1", service_type="bedrock")
        )


async def test_cloudflare_tcp_rejects_udp_target_at_creation(monkeypatch):
    """Test 13: Attempting to add a UDP target when method is cloudflare_tcp returns 422."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()

    fake_client = FakeCloudflareClient()
    monkeypatch.setattr(exposure_commands, "CloudflareClient", lambda _token: fake_client)
    sup = FakeServerSupervisor("srv-1")
    monkeypatch.setattr(exposure_commands, "get_server_cloudflared_supervisor", lambda _: sup)

    # Create Java target first
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="java")
    )

    # Enable Cloudflare TCP on Java target first
    await SetServerExposureHandler(bus).handle(
        SetServerExposureCommand(
            server_id="srv-1",
            method="cloudflare_tcp",
            desired_state="ENABLED",
            cloudflare_token=_API_TOKEN,
            hostname=_HOSTNAME,
            acknowledged_warning=True,
        )
    )

    # Register Bedrock UDP port
    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1", service_type="bedrock", protocol="udp", port=19132
        )
    )

    # Attempt to create Bedrock target -> rejected
    with pytest.raises(MethodProtocolIncompatibleError):
        await CreateExposureTargetHandler(bus).handle(
            CreateExposureTargetCommand(server_id="srv-1", service_type="bedrock")
        )


async def test_cloudflare_tcp_rejects_enable_with_udp_target():
    """Test 14: Enabling cloudflare_tcp on a server with existing UDP targets returns 422."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()

    # Register Bedrock UDP port and create target under playit method
    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1", service_type="bedrock", protocol="udp", port=19132
        )
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="bedrock")
    )

    # Attempt to switch/enable Cloudflare TCP
    with pytest.raises(MethodProtocolIncompatibleError):
        await SetServerExposureHandler(bus).handle(
            SetServerExposureCommand(
                server_id="srv-1",
                method="cloudflare_tcp",
                desired_state="ENABLED",
                cloudflare_token=_API_TOKEN,
                hostname=_HOSTNAME,
                acknowledged_warning=True,
            )
        )


async def test_cloudflare_tcp_allows_bluemap_tcp_target(monkeypatch):
    """Test 15: Cloudflare TCP successfully exposes Java TCP and BlueMap TCP targets."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()

    fake_client = FakeCloudflareClient()
    monkeypatch.setattr(exposure_commands, "CloudflareClient", lambda _token: fake_client)
    sup = FakeServerSupervisor("srv-1")
    monkeypatch.setattr(exposure_commands, "get_server_cloudflared_supervisor", lambda _: sup)

    # Create Java target
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(
            server_id="srv-1", service_type="java", public_address="mc.example.com"
        )
    )
    # Register BlueMap TCP port and create target
    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1", service_type="bluemap", protocol="tcp", port=8100
        )
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(
            server_id="srv-1", service_type="bluemap", public_address="map.example.com"
        )
    )

    # Enable Cloudflare TCP
    res = await SetServerExposureHandler(bus).handle(
        SetServerExposureCommand(
            server_id="srv-1",
            method="cloudflare_tcp",
            desired_state="ENABLED",
            cloudflare_token=_API_TOKEN,
            hostname="mc.example.com",
            acknowledged_warning=True,
        )
    )

    assert res.success is True
    assert len(fake_client.ingresses) == 1
    rules = fake_client.ingresses[0][1]
    assert len(rules) == 3  # Java TCP + BlueMap TCP + 404
    assert rules[0] == {"hostname": "mc.example.com", "service": "tcp://127.0.0.1:25565"}
    assert rules[1] == {"hostname": "map.example.com", "service": "tcp://127.0.0.1:8100"}
    assert rules[2] == {"service": "http_status:404"}


async def test_upnp_maps_udp_protocol_correctly(monkeypatch):
    """Test 16: UPnP port forward for Bedrock passes protocol='UDP' to AsyncUPnPService."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()

    fake_upnp = FakeUPnPService()
    monkeypatch.setattr(exposure_commands, "AsyncUPnPService", lambda: fake_upnp)

    # Create Java target first
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="java")
    )

    # Enable UPnP with Java target
    await SetServerExposureHandler(bus).handle(
        SetServerExposureCommand(server_id="srv-1", method="port_forward", desired_state="ENABLED")
    )

    # Register Bedrock and create target
    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1", service_type="bedrock", protocol="udp", port=19132
        )
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="bedrock")
    )

    # Check that attempt_mapping was called with UDP
    udp_attempts = [a for a in fake_upnp.attempts if a["protocol"] == "UDP"]
    assert len(udp_attempts) == 1
    assert udp_attempts[0]["internal_port"] == 19132


async def test_upnp_multi_target_mapping_and_deletion(monkeypatch):
    """Test 17: Enabling UPnP maps both TCP and UDP ports; disabling deletes both mappings."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()

    fake_upnp = FakeUPnPService()
    monkeypatch.setattr(exposure_commands, "AsyncUPnPService", lambda: fake_upnp)

    # Register Bedrock
    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1", service_type="bedrock", protocol="udp", port=19132
        )
    )

    # Create Java & Bedrock targets
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="java")
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="bedrock")
    )

    # Enable UPnP
    await SetServerExposureHandler(bus).handle(
        SetServerExposureCommand(server_id="srv-1", method="port_forward", desired_state="ENABLED")
    )

    mapped_protocols = {a["protocol"] for a in fake_upnp.attempts}
    assert mapped_protocols == {"TCP", "UDP"}

    # Disable UPnP
    await DisableServerExposureHandler(bus).handle(DisableServerExposureCommand(server_id="srv-1"))

    deleted_protocols = {d["protocol"] for d in fake_upnp.deletions}
    assert deleted_protocols == {"TCP", "UDP"}


async def test_playit_multi_target_allocation():
    """Test 18: playit provisions target setup instructions for Java TCP and Bedrock UDP."""
    await _seed_claimed_agent()
    await _create_test_server("srv-1", 25565)
    bus = EventBus()

    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1", service_type="bedrock", protocol="udp", port=19132
        )
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="java")
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="bedrock")
    )

    await EnableServerExposureHandler(bus).handle(EnableServerExposureCommand(server_id="srv-1"))

    targets = await ListExposureTargetsHandler().handle(ListExposureTargetsQuery(server_id="srv-1"))
    assert len(targets) == 2
    bedrock = next(t for t in targets if t["service_type"] == "bedrock")
    assert "Bedrock (UDP)" in bedrock["setup_instructions"]
    assert "19132" in bedrock["setup_instructions"]


async def test_delete_registered_port_cleans_active_target(monkeypatch):
    """Test 19: Deleting registered port removes active target and tears down mapping."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()

    fake_upnp = FakeUPnPService()
    monkeypatch.setattr(exposure_commands, "AsyncUPnPService", lambda: fake_upnp)

    reg_res = await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1", service_type="bedrock", protocol="udp", port=19132
        )
    )
    port_id = reg_res.data["id"]

    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="java")
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="bedrock")
    )

    await SetServerExposureHandler(bus).handle(
        SetServerExposureCommand(server_id="srv-1", method="port_forward", desired_state="ENABLED")
    )

    # Delete port
    del_res = await DeleteServerPortHandler(bus).handle(
        DeleteServerPortCommand(server_id="srv-1", port_id=port_id)
    )
    assert del_res.success is True

    # Check targets remaining -> only Java
    targets = await ListExposureTargetsHandler().handle(ListExposureTargetsQuery(server_id="srv-1"))
    assert len(targets) == 1
    assert targets[0]["service_type"] == "java"

    # Check UPnP deletion called for UDP port 19132
    udp_deletions = [d for d in fake_upnp.deletions if d["protocol"] == "UDP"]
    assert len(udp_deletions) == 1
    assert udp_deletions[0]["port"] == 19132


async def test_backward_compat_target_create_omitted_fields():
    """Test 20: Legacy target creation auto-creates Java TCP target using ServerModel.port."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()

    # Call handler with only server_id (all 7.3d fields omitted)
    res = await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1")
    )
    assert res.success is True
    assert res.data["service_type"] == "java"
    assert res.data["protocol"] == "tcp"
    assert res.data["local_port"] == 25565


async def test_aggregate_status_fold_multi_target(monkeypatch):
    """Test 21: Aggregate status folds 1 ACTIVE + 1 ERROR target into ERROR."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()

    fake_upnp = FakeUPnPService()

    # Mock attempt_mapping so Java succeeds (active) and Bedrock fails (error)
    async def _mock_attempt(internal_port, requested_external_port, description, protocol="TCP"):
        _ = (internal_port, description)
        if protocol == "UDP":
            return UPnPResult(
                success=False, error_code="UPNP_TIMEOUT", error_message="Router timeout"
            )
        return UPnPResult(
            success=True, external_ip="1.2.3.4", external_port=requested_external_port
        )

    fake_upnp.attempt_mapping = _mock_attempt
    monkeypatch.setattr(exposure_commands, "AsyncUPnPService", lambda: fake_upnp)

    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1", service_type="bedrock", protocol="udp", port=19132
        )
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="java")
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="bedrock")
    )

    res = await SetServerExposureHandler(bus).handle(
        SetServerExposureCommand(server_id="srv-1", method="port_forward", desired_state="ENABLED")
    )

    assert res.data["aggregate_status"] == ExposureStatus.ERROR.value


async def test_single_method_per_server_enforced():
    """Test 22: Changing server exposure method switches all targets to the new method."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()

    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1", service_type="bedrock", protocol="udp", port=19132
        )
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="java")
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="bedrock")
    )

    # Initial method is playit
    exp = await GetServerExposureHandler().handle(GetServerExposureQuery(server_id="srv-1"))
    assert exp["method"] == ExposureMethod.PLAYIT.value

    # Switch method to port_forward
    res = await SetServerExposureHandler(bus).handle(
        SetServerExposureCommand(server_id="srv-1", method="port_forward", desired_state="DISABLED")
    )
    assert res.data["method"] == ExposureMethod.PORT_FORWARD.value


async def test_stop_all_exposures_cleans_multi_targets(monkeypatch):
    """Test 23: Global stop action terminates all TCP and UDP mappings across all servers."""
    await _create_test_server("srv-1", 25565)
    await _create_test_server("srv-2", 25566)
    bus = EventBus()

    fake_upnp = FakeUPnPService()
    monkeypatch.setattr(exposure_commands, "AsyncUPnPService", lambda: fake_upnp)

    # Server 1: Java TCP + Bedrock UDP
    await RegisterServerPortHandler(bus).handle(
        RegisterServerPortCommand(
            server_id="srv-1", service_type="bedrock", protocol="udp", port=19132
        )
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="java")
    )
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-1", service_type="bedrock")
    )
    await SetServerExposureHandler(bus).handle(
        SetServerExposureCommand(server_id="srv-1", method="port_forward", desired_state="ENABLED")
    )

    # Server 2: Java TCP
    await CreateExposureTargetHandler(bus).handle(
        CreateExposureTargetCommand(server_id="srv-2", service_type="java")
    )
    await SetServerExposureHandler(bus).handle(
        SetServerExposureCommand(server_id="srv-2", method="port_forward", desired_state="ENABLED")
    )

    # Stop all
    res = await StopAllExposuresHandler(bus).handle(StopAllExposuresCommand())
    assert res.success is True
    assert res.data["disabled_count"] == 2

    # Check that both TCP and UDP mappings were deleted
    deleted_protocols = {d["protocol"] for d in fake_upnp.deletions}
    assert deleted_protocols == {"TCP", "UDP"}


async def test_port_registration_rbac_permissions():
    """Test 24: Port registration endpoints and handlers reject non-existent servers."""
    bus = EventBus()
    handler = RegisterServerPortHandler(bus)

    with pytest.raises(NotFoundError):
        await handler.handle(
            RegisterServerPortCommand(
                server_id="srv-nonexistent",
                service_type="bedrock",
                protocol="udp",
                port=19132,
            )
        )


async def test_set_server_exposure_auto_creates_java_target_when_empty(monkeypatch):
    """Test 25: Enabling exposure on a server without targets auto-creates the Java target."""
    await _create_test_server("srv-new", 25565)
    bus = EventBus()

    # Initial exposure query for new server returns default unexposed state
    initial_exp = await GetServerExposureHandler().handle(
        GetServerExposureQuery(server_id="srv-new")
    )
    assert initial_exp["server_id"] == "srv-new"
    assert initial_exp["method"] == "none"
    assert initial_exp["desired_state"] == "DISABLED"
    assert initial_exp["targets"] == []

    # Mock UPnP service for port forwarding enable
    fake_upnp = FakeUPnPService()
    monkeypatch.setattr(exposure_commands, "AsyncUPnPService", lambda: fake_upnp)

    # Enable exposure without pre-creating targets
    res = await SetServerExposureHandler(bus).handle(
        SetServerExposureCommand(
            server_id="srv-new", method="port_forward", desired_state="ENABLED"
        )
    )
    assert res.success is True
    assert res.data["desired_state"] == "ENABLED"
    assert res.data["method"] == "port_forward"
    assert len(res.data["targets"]) == 1
    assert res.data["targets"][0]["service_type"] == "java"
    assert res.data["targets"][0]["protocol"] == "tcp"
    assert res.data["targets"][0]["local_port"] == 25565


async def test_get_server_exposure_returns_not_found_for_nonexistent_server():
    """Test 26: GetServerExposureQuery rejects non-existent servers with NotFoundError."""
    with pytest.raises(NotFoundError):
        await GetServerExposureHandler().handle(GetServerExposureQuery(server_id="srv-nonexistent"))
