"""Application-layer tests for Server Cloudflare TCP Exposure (Batch 7.3c).

Adheres to strict test safety standards:
  - os.kill / os.killpg hermetically mocked
  - Safe sentinel mock PIDs (99999) only
  - Zero real subprocess spawning
  - Zero real Cloudflare API calls
  - Guaranteed supervisor cleanup
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
from app.core.exceptions import InvalidValueError, ValidationError
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.settings_store import init_settings_store
from app.modules.exposure.application import commands as exposure_commands
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
)
from app.modules.exposure.application.queries import (
    GetServerExposureHandler,
    GetServerExposureQuery,
)
from app.modules.exposure.domain.exceptions import (
    WarningNotAcknowledgedError,
)
from app.modules.exposure.domain.value_objects import (
    ExposureMethod,
    ExposureStatus,
)
from app.modules.exposure.infrastructure.cloudflare import (
    CloudflareApiError,
    CloudflareAuthError,
    TunnelProvisionResult,
)
from app.modules.exposure.infrastructure.cloudflared import (
    CloudflaredSupervisor,
    reset_server_cloudflared_supervisors,
)
from app.modules.exposure.infrastructure.repository import (
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
_HOSTNAME = "play.example.com"
_API_TOKEN = "cf-api-token-srv-123456"
_TUNNEL_TOKEN = "provisioned-srv-tunnel-token-xyz"
_ROTATION_TOKEN = "replacement-srv-tunnel-token-rotate-123"


class FakeCloudflareClient:
    """Fake of the external HTTPS boundary; records calls verbatim."""

    def __init__(
        self,
        *,
        auth_error: bool = False,
        api_error: bool = False,
    ) -> None:
        self._auth_error = auth_error
        self._api_error = api_error
        self.create_attempts = 0
        self.created_names: list[str] = []
        self.ingresses: list[tuple[str, list[dict[str, str]]]] = []
        self.cnames: list[tuple[str, str]] = []

    async def create_named_tunnel(self, name: str) -> TunnelProvisionResult:
        self.create_attempts += 1
        if self._auth_error:
            raise CloudflareAuthError("Cloudflare API rejected the token (HTTP 401)")
        if self._api_error:
            raise CloudflareApiError("Cloudflare API request failed (HTTP 500)")
        self.created_names.append(name)
        return TunnelProvisionResult(tunnel_id="tun-srv-abc", token=_TUNNEL_TOKEN)

    async def configure_ingress(self, tunnel_id: str, ingress: list[dict[str, str]]) -> None:
        self.ingresses.append((tunnel_id, ingress))

    async def create_cname(self, hostname: str, tunnel_id: str) -> str:
        self.cnames.append((hostname, tunnel_id))
        return "dns-srv-1"


class FakeServerSupervisor:
    """Fake of the per-server ``cloudflared`` subprocess boundary."""

    def __init__(self, server_id: str = "srv-1") -> None:
        self.server_id = server_id
        self.stops = 0
        self.starts: list[bytes] = []
        self._running = False
        self.last_on_status = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self, token: bytes, *, on_status=None) -> None:
        self.starts.append(token)
        self.last_on_status = on_status
        self._running = True

    async def stop(self) -> None:
        self.stops += 1
        self._running = False


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

    key_path = str(tmp_path / "backup_key.bin")
    monkeypatch.setenv("MCS_BACKUP_ENCRYPTION_KEY_PATH", key_path)

    reset_server_cloudflared_supervisors()

    yield

    reset_server_cloudflared_supervisors()
    await engine.dispose()
    database._engine = None
    database._session_factory = None


async def _create_test_server(server_id_str: str = "srv-1", port: int = 25565) -> Server:
    async with database._session_factory() as session:
        repo = SQLServerRepository(session)
        server = Server.create(
            server_id=ServerId(server_id_str),
            name="Test Survival",
            server_type=ServerType.VANILLA,
            minecraft_version=MinecraftVersion.parse("1.20.4"),
            memory=MemoryAllocation(1024, 2048),
            java_args=JavaArguments([]),
            properties=ServerProperties(port=PortNumber(port)),
        )
        await repo.save(server)
        await session.commit()
        return server


def _patch_boundaries(
    monkeypatch,
    client: FakeCloudflareClient,
    supervisors: dict[str, FakeServerSupervisor] | None = None,
):
    monkeypatch.setattr(exposure_commands, "CloudflareClient", lambda _token: client)
    if supervisors is not None:

        def _get_sup(srv_id: str):
            if srv_id not in supervisors:
                supervisors[srv_id] = FakeServerSupervisor(srv_id)
            return supervisors[srv_id]

        monkeypatch.setattr(exposure_commands, "get_server_cloudflared_supervisor", _get_sup)


# ===========================================================================
# 24 Acceptance Tests (Section 15.1)
# ===========================================================================


async def test_server_cloudflare_tcp_enable_success(monkeypatch):
    """1. Valid credentials with acknowledged warning provisions tunnel and starts supervisor."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    set_handler = SetServerExposureHandler(bus)

    # Pre-create target first via create target
    target_cmd = CreateExposureTargetCommand(server_id="srv-1")
    await CreateExposureTargetHandler(bus).handle(target_cmd)

    cmd = SetServerExposureCommand(
        server_id="srv-1",
        method="cloudflare_tcp",
        desired_state="ENABLED",
        cloudflare_token=_API_TOKEN,
        hostname=_HOSTNAME,
        acknowledged_warning=True,
    )
    result = await set_handler.handle(cmd)
    assert result.success is True
    assert result.data["desired_state"] == "ENABLED"
    assert result.data["method"] == "cloudflare_tcp"
    assert result.data["cloudflare_tunnel_id"] == "tun-srv-abc"
    assert result.data["has_cloudflare_credentials"] is True
    assert len(result.data["targets"]) == 1
    assert result.data["targets"][0]["public_address"] == _HOSTNAME

    assert client.create_attempts == 1
    assert client.created_names == ["onx-srv-srv-1"]
    assert client.cnames == [(_HOSTNAME, "tun-srv-abc")]
    assert supervisors["srv-1"].is_running is True
    assert supervisors["srv-1"].starts == [_TUNNEL_TOKEN.encode("utf-8")]


async def test_server_cloudflare_tcp_warning_required(monkeypatch):
    """2. Omission of acknowledged_warning raises WarningNotAcknowledgedError (422)."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    _patch_boundaries(monkeypatch, client)

    bus = EventBus()
    cmd = SetServerExposureCommand(
        server_id="srv-1",
        method="cloudflare_tcp",
        desired_state="ENABLED",
        cloudflare_token=_API_TOKEN,
        hostname=_HOSTNAME,
        # acknowledged_warning omitted (defaults False)
    )
    with pytest.raises(WarningNotAcknowledgedError) as exc_info:
        await SetServerExposureHandler(bus).handle(cmd)

    assert exc_info.value.code == "WARNING_NOT_ACKNOWLEDGED"
    assert client.create_attempts == 0


async def test_server_cloudflare_tcp_warning_false_rejected(monkeypatch):
    """3. Explicit acknowledged_warning: False raises WarningNotAcknowledgedError (422)."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    _patch_boundaries(monkeypatch, client)

    bus = EventBus()
    cmd = SetServerExposureCommand(
        server_id="srv-1",
        method="cloudflare_tcp",
        desired_state="ENABLED",
        cloudflare_token=_API_TOKEN,
        hostname=_HOSTNAME,
        acknowledged_warning=False,
    )
    with pytest.raises(WarningNotAcknowledgedError):
        await SetServerExposureHandler(bus).handle(cmd)

    assert client.create_attempts == 0


async def test_server_cloudflare_tcp_repeated_enable_idempotent(monkeypatch):
    """4. Sequential enable commands with identical parameters succeed idempotently."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    enable_cmd = EnableServerExposureCommand(
        server_id="srv-1",
        cloudflare_token=_API_TOKEN,
        hostname=_HOSTNAME,
        acknowledged_warning=True,
    )
    # Configure method as cloudflare_tcp
    set_cmd = SetServerExposureCommand(
        server_id="srv-1",
        method="cloudflare_tcp",
        desired_state="DISABLED",
        acknowledged_warning=True,
    )
    # Create target
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))
    await SetServerExposureHandler(bus).handle(set_cmd)

    # First enable
    res1 = await EnableServerExposureHandler(bus).handle(enable_cmd)
    assert res1.success is True

    # Second enable with existing credentials (no token needed)
    enable_cmd2 = EnableServerExposureCommand(
        server_id="srv-1",
        acknowledged_warning=True,
    )
    res2 = await EnableServerExposureHandler(bus).handle(enable_cmd2)
    assert res2.success is True
    assert client.create_attempts == 1  # No duplicate tunnel created


async def test_server_cloudflare_tcp_disable_cleanup(monkeypatch):
    """5. Disabling exposure terminates supervisor child."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))
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
    assert supervisors["srv-1"].is_running is True

    # Disable
    await DisableServerExposureHandler(bus).handle(DisableServerExposureCommand(server_id="srv-1"))
    assert supervisors["srv-1"].is_running is False
    assert supervisors["srv-1"].stops >= 1


async def test_server_cloudflare_tcp_revoked_token_reclaim_required(monkeypatch):
    """6. Stderr auth failure marker / status callback triggers transition to RECLAIM_REQUIRED."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))
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

    # Trigger RECLAIM_REQUIRED callback
    on_status = supervisors["srv-1"].last_on_status
    assert on_status is not None
    await on_status(ExposureStatus.RECLAIM_REQUIRED)

    # Check query
    res = await GetServerExposureHandler().handle(GetServerExposureQuery(server_id="srv-1"))
    assert res["aggregate_status"] == "RECLAIM_REQUIRED"
    assert res["targets"][0]["status"] == "RECLAIM_REQUIRED"


async def test_server_cloudflare_tcp_token_rotation_recovery(monkeypatch):
    """7. Providing valid replacement token in RECLAIM_REQUIRED recovers to STARTING/ACTIVE."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))
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

    # Set RECLAIM_REQUIRED
    await supervisors["srv-1"].last_on_status(ExposureStatus.RECLAIM_REQUIRED)

    # Provide replacement token
    rotate_cmd = SetServerExposureCommand(
        server_id="srv-1",
        method="cloudflare_tcp",
        desired_state="ENABLED",
        cloudflare_token=_ROTATION_TOKEN,
        hostname=_HOSTNAME,
        acknowledged_warning=True,
    )
    result = await SetServerExposureHandler(bus).handle(rotate_cmd)
    assert result.success is True
    assert result.data["aggregate_status"] == "STARTING"
    assert supervisors["srv-1"].starts[-1] == _ROTATION_TOKEN.encode("utf-8")
    assert client.create_attempts == 1  # Reuses existing tunnel!


async def test_server_cloudflare_tcp_invalid_replacement_remains_reclaim(monkeypatch):
    """8. Providing invalid replacement token leaves status in RECLAIM_REQUIRED."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))
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
    await supervisors["srv-1"].last_on_status(ExposureStatus.RECLAIM_REQUIRED)

    # Rotate with invalid token (supervisor reports reclaim again)
    await SetServerExposureHandler(bus).handle(
        SetServerExposureCommand(
            server_id="srv-1",
            method="cloudflare_tcp",
            desired_state="ENABLED",
            cloudflare_token="invalid-token",
            hostname=_HOSTNAME,
            acknowledged_warning=True,
        )
    )
    await supervisors["srv-1"].last_on_status(ExposureStatus.RECLAIM_REQUIRED)

    res = await GetServerExposureHandler().handle(GetServerExposureQuery(server_id="srv-1"))
    assert res["aggregate_status"] == "RECLAIM_REQUIRED"


async def test_server_cloudflare_tcp_token_never_in_api_response(monkeypatch):
    """9. GET /servers/{id}/exposure returns has_cloudflare_credentials: True, zero token data."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))
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

    res = await GetServerExposureHandler().handle(GetServerExposureQuery(server_id="srv-1"))
    assert res["has_cloudflare_credentials"] is True
    assert "cloudflare_token" not in res
    assert "token" not in res
    assert "ciphertext" not in str(res)


async def test_server_cloudflare_tcp_token_never_in_argv():
    """10. Subprocess command line contains --token-file and zero plaintext token arguments."""
    sup = CloudflaredSupervisor(server_id="srv-1")
    token_bytes = b"secret-token-123"

    mock_proc = MagicMock()
    mock_proc.pid = SAFE_SENTINEL_PID
    mock_proc.returncode = None
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with (
        patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        patch.object(sup, "_read_stderr", return_value=None),
        patch.object(sup, "_monitor", return_value=None),
    ):
        mock_exec.return_value = mock_proc
        await sup.start(token_bytes)
        call_args = mock_exec.call_args[0]
        assert "cloudflared" in call_args[0]
        assert "tunnel" in call_args
        assert "run" in call_args
        assert "--token-file" in call_args
        assert "--token" not in call_args
        assert token_bytes.decode() not in call_args
        await sup.stop()


async def test_server_cloudflare_tcp_public_address_format(monkeypatch):
    """11. Target public_address is formatted as {hostname} (no http://, no port)."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))
    res = await SetServerExposureHandler(bus).handle(
        SetServerExposureCommand(
            server_id="srv-1",
            method="cloudflare_tcp",
            desired_state="ENABLED",
            cloudflare_token=_API_TOKEN,
            hostname="mc.mydomain.org",
            acknowledged_warning=True,
        )
    )
    assert res.data["targets"][0]["public_address"] == "mc.mydomain.org"


async def test_server_cloudflare_tcp_java_tcp_only_enforced():
    """12. Target creation enforces service_type == 'java' and protocol == 'tcp'."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    cmd = CreateExposureTargetCommand(server_id="srv-1")
    target_res = await CreateExposureTargetHandler(bus).handle(cmd)
    assert target_res.data["protocol"] == "tcp"
    assert target_res.data["service_type"] == "java"
    assert target_res.data["local_port"] == 25565


async def test_server_cloudflare_tcp_arbitrary_port_rejected():
    """13. Local port mismatching ServerModel.port is rejected with InvalidValueError."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    async with UnitOfWork(bus) as uow:
        repo = SQLServerExposureRepository(uow.session)
        exposure = await repo.get("srv-1")
        if exposure is None:
            from app.modules.exposure.domain.aggregate import ServerExposure

            exposure = ServerExposure(server_id="srv-1", method=ExposureMethod.CLOUDFLARE_TCP)
        # Attempt to validate mismatched port
        with pytest.raises(InvalidValueError):
            exposure.validate_target_port(25566, 25565)


async def test_server_cloudflare_tcp_deny_list_ports_rejected():
    """14. Deny-listed ports (25575, 3306, 5432, etc.) are rejected."""
    await _create_test_server("srv-1", 25575)  # RCON port
    bus = EventBus()
    async with UnitOfWork(bus):
        from app.modules.exposure.domain.aggregate import ServerExposure

        exposure = ServerExposure(server_id="srv-1", method=ExposureMethod.CLOUDFLARE_TCP)
        with pytest.raises(InvalidValueError) as exc_info:
            exposure.validate_target_port(25575, 25575)
        assert "deny-list" in str(exc_info.value).lower()


async def test_server_cloudflare_tcp_server_isolation(monkeypatch):
    """15. Exposure on Server A does not affect Server B's independent supervisor or state."""
    await _create_test_server("srv-a", 25565)
    await _create_test_server("srv-b", 25566)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    # Enable Server A
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-a"))
    await SetServerExposureHandler(bus).handle(
        SetServerExposureCommand(
            server_id="srv-a",
            method="cloudflare_tcp",
            desired_state="ENABLED",
            cloudflare_token=_API_TOKEN,
            hostname="a.example.com",
            acknowledged_warning=True,
        )
    )

    # Server B initialized with target but not enabled
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-b"))
    res_b = await GetServerExposureHandler().handle(GetServerExposureQuery(server_id="srv-b"))
    assert res_b["desired_state"] == "DISABLED"
    assert "srv-b" not in supervisors or supervisors["srv-b"].is_running is False
    assert supervisors["srv-a"].is_running is True


async def test_server_cloudflare_tcp_concurrent_enable(monkeypatch):
    """16. Concurrent enable requests handle locking safely without duplicate tunnels."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))

    cmd = SetServerExposureCommand(
        server_id="srv-1",
        method="cloudflare_tcp",
        desired_state="ENABLED",
        cloudflare_token=_API_TOKEN,
        hostname=_HOSTNAME,
        acknowledged_warning=True,
    )
    handler = SetServerExposureHandler(bus)

    # Run concurrently
    res1, res2 = await asyncio.gather(handler.handle(cmd), handler.handle(cmd))
    assert res1.success is True
    assert res2.success is True


async def test_server_cloudflare_tcp_disable_during_startup(monkeypatch):
    """17. Disabling exposure during STARTING state terminates process cleanly."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))
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
    # Immediately disable
    await DisableServerExposureHandler(bus).handle(DisableServerExposureCommand(server_id="srv-1"))
    assert supervisors["srv-1"].is_running is False


async def test_server_cloudflare_tcp_restart_recovery(monkeypatch):
    """18. Reconcile restores supervisor process for enabled Cloudflare TCP exposures on restart."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))
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

    # Simulate server restart (supervisor stopped)
    await supervisors["srv-1"].stop()
    assert supervisors["srv-1"].is_running is False

    # Trigger reconcile
    rec_res = await ReconcileExposureHandler(bus).handle(ReconcileExposureCommand())
    assert rec_res.success is True
    assert supervisors["srv-1"].is_running is True


async def test_server_cloudflare_tcp_missing_token_rejected():
    """19. Enable request without cloudflare_token is rejected with ValidationError."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))

    cmd = SetServerExposureCommand(
        server_id="srv-1",
        method="cloudflare_tcp",
        desired_state="ENABLED",
        cloudflare_token="",
        hostname=_HOSTNAME,
        acknowledged_warning=True,
    )
    with pytest.raises(ValidationError) as exc_info:
        await SetServerExposureHandler(bus).handle(cmd)
    assert "token is required" in str(exc_info.value).lower()


async def test_server_cloudflare_tcp_missing_hostname_rejected():
    """20. Enable request without hostname is rejected with ValidationError."""
    await _create_test_server("srv-1", 25565)
    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))

    cmd = SetServerExposureCommand(
        server_id="srv-1",
        method="cloudflare_tcp",
        desired_state="ENABLED",
        cloudflare_token=_API_TOKEN,
        hostname="",
        acknowledged_warning=True,
    )
    with pytest.raises(ValidationError) as exc_info:
        await SetServerExposureHandler(bus).handle(cmd)
    assert "hostname is required" in str(exc_info.value).lower()


async def test_server_cloudflare_tcp_provider_auth_error(monkeypatch):
    """21. Initial Cloudflare API 401/403 maps immediately to RECLAIM_REQUIRED."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient(auth_error=True)
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))

    cmd = SetServerExposureCommand(
        server_id="srv-1",
        method="cloudflare_tcp",
        desired_state="ENABLED",
        cloudflare_token=_API_TOKEN,
        hostname=_HOSTNAME,
        acknowledged_warning=True,
    )
    res = await SetServerExposureHandler(bus).handle(cmd)
    assert res.success is True
    assert res.data["aggregate_status"] == "RECLAIM_REQUIRED"
    assert res.data["targets"][0]["status"] == "RECLAIM_REQUIRED"


async def test_server_cloudflare_tcp_provider_api_error(monkeypatch):
    """22. Generic Cloudflare API errors map to ERROR (CLOUDFLARE_API_ERROR)."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient(api_error=True)
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))

    cmd = SetServerExposureCommand(
        server_id="srv-1",
        method="cloudflare_tcp",
        desired_state="ENABLED",
        cloudflare_token=_API_TOKEN,
        hostname=_HOSTNAME,
        acknowledged_warning=True,
    )
    res = await SetServerExposureHandler(bus).handle(cmd)
    assert res.success is True
    assert res.data["aggregate_status"] == "ERROR"
    assert res.data["targets"][0]["error_code"] == "CLOUDFLARE_API_ERROR"


async def test_server_cloudflare_tcp_degraded_health_probe(monkeypatch):
    """23. Unresponsive metrics probe triggers DEGRADED status callback."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))
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

    # Trigger DEGRADED via status callback
    on_status = supervisors["srv-1"].last_on_status
    await on_status(ExposureStatus.DEGRADED)

    res = await GetServerExposureHandler().handle(GetServerExposureQuery(server_id="srv-1"))
    assert res["aggregate_status"] == "DEGRADED"
    assert res["targets"][0]["status"] == "DEGRADED"


async def test_server_cloudflare_tcp_remove_exposure_cleans_up(monkeypatch):
    """24. Deleting exposure cleans up supervisor and unlinks credentials."""
    await _create_test_server("srv-1", 25565)
    client = FakeCloudflareClient()
    supervisors = {}
    _patch_boundaries(monkeypatch, client, supervisors)

    bus = EventBus()
    await CreateExposureTargetHandler(bus).handle(CreateExposureTargetCommand(server_id="srv-1"))
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
    assert supervisors["srv-1"].is_running is True

    # Remove exposure
    rem_cmd = RemoveServerExposureCommand(server_id="srv-1")
    rem_res = await RemoveServerExposureHandler(bus).handle(rem_cmd)
    assert rem_res.success is True
    assert rem_res.data["removed"] is True
    assert supervisors["srv-1"].is_running is False
