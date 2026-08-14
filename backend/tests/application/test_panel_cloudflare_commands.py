"""Application-level tests for the real SetPanelExposure orchestration (Batch 7.2a).

These exercise the REAL handler + REAL UnitOfWork + REAL sqlite DB + REAL
AES-GCM encryption. Only the two external boundaries are faked:
  - ``CloudflareClient`` (the Cloudflare HTTPS API)
  - ``get_cloudflared_supervisor`` (the ``cloudflared`` child subprocess)

The handler orchestration itself (validation -> provision tunnel -> configure
ingress -> single CNAME -> encrypt -> persist -> post-commit supervisor start)
runs unmodified.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.modules.auth.infrastructure.models  # noqa: F401  (users FK target)
import app.modules.exposure.infrastructure.models  # noqa: F401  (tables under test)
import app.modules.server.infrastructure.models  # noqa: F401  (servers FK target)
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.exposure.application.commands import (
    ReconcileExposureCommand,
    ReconcileExposureHandler,
    SetPanelExposureCommand,
    SetPanelExposureHandler,
    _panel_payload,
    _persist_panel_status,
)
from app.modules.exposure.domain.aggregate import PanelExposure
from app.modules.exposure.domain.value_objects import DesiredState, ExposureStatus
from app.modules.exposure.infrastructure.cloudflare import TunnelProvisionResult
from app.modules.exposure.infrastructure.repository import SQLPanelExposureRepository
from app.modules.storage.encryption import build_backup_encryption

pytestmark = pytest.mark.asyncio

_HOSTNAME = "panel.example.com"
_API_TOKEN = "cf-api-token-abcdef123456"
_TUNNEL_TOKEN = "provisioned-tunnel-token-xyz"
_ROTATION_TOKEN = "replacement-tunnel-token-rotate-123"
_INVALID_ROTATION_TOKEN = "replacement-tunnel-token-invalid-999"


class FakeCloudflareClient:
    """Fake of the external HTTPS boundary; records every call verbatim."""

    def __init__(self, *, auth_error: bool = False) -> None:
        self._auth_error = auth_error
        self.create_attempts = 0
        self.created_names: list[str] = []
        self.ingresses: list[tuple[str, list[dict[str, str]]]] = []
        self.cnames: list[tuple[str, str]] = []

    async def create_named_tunnel(self, name: str) -> TunnelProvisionResult:
        self.create_attempts += 1
        if self._auth_error:
            from app.modules.exposure.infrastructure.cloudflare import (
                CloudflareAuthError,
            )

            raise CloudflareAuthError("Cloudflare API rejected the token (HTTP 401)")
        self.created_names.append(name)
        return TunnelProvisionResult(tunnel_id="tun-abc", token=_TUNNEL_TOKEN)

    async def configure_ingress(self, tunnel_id: str, ingress: list[dict[str, str]]) -> None:
        self.ingresses.append((tunnel_id, ingress))

    async def create_cname(self, hostname: str, tunnel_id: str) -> str:
        self.cnames.append((hostname, tunnel_id))
        return "dns-1"


class FakeSupervisor:
    """Fake of the ``cloudflared`` subprocess boundary."""

    def __init__(self) -> None:
        self.stops = 0
        self.starts: list[bytes] = []
        self._running = False

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
async def _exposure_db():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    yield
    await engine.dispose()
    database._engine = None
    database._session_factory = None


@pytest.fixture
def key_path(tmp_path, monkeypatch) -> str:
    path = str(tmp_path / "backup_encryption_key.bin")
    monkeypatch.setenv("MCS_BACKUP_ENCRYPTION_KEY_PATH", path)
    return path


@pytest.fixture(autouse=True)
def _auto_key_path(key_path) -> str:
    return key_path


def _patch_boundaries(monkeypatch, client, supervisor):
    from app.modules.exposure.application import commands as exposure_commands

    monkeypatch.setattr(exposure_commands, "CloudflareClient", lambda _token: client)
    monkeypatch.setattr(exposure_commands, "get_cloudflared_supervisor", lambda: supervisor)


async def _load_panel() -> PanelExposure:
    async with database._session_factory() as session:
        repo = SQLPanelExposureRepository(session)
        return await repo.get()


async def _set_panel_reclaim_required() -> None:
    """Simulate the runtime reclaim: cloudflared reported an invalid/revoked
    tunnel token, the supervisor feedback persisted RECLAIM_REQUIRED while the
    stored credentials (tunnel id + ciphertext) were kept."""
    async with database._session_factory() as session:
        repo = SQLPanelExposureRepository(session)
        panel = await repo.get()
        panel.set_status(ExposureStatus.RECLAIM_REQUIRED)
        panel.set_error(
            "RECLAIM_REQUIRED", "cloudflared reported an invalid/revoked tunnel token"
        )
        await repo.save(panel)
        await session.commit()


class TestSetPanelExposureEnable:
    async def test_enable_full_orchestration_persists_encrypted_token(
        self, key_path, monkeypatch
    ) -> None:
        client = FakeCloudflareClient()
        supervisor = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, supervisor)
        handler = SetPanelExposureHandler(event_bus=EventBus())

        result = await handler.handle(
            SetPanelExposureCommand(
                method="cloudflare_tunnel",
                desired_state="ENABLED",
                cloudflare_token=_API_TOKEN,
                hostname=_HOSTNAME,
            )
        )

        # Handler-level assertions.
        assert result.success
        data = result.data
        assert data["method"] == "cloudflare_tunnel"
        assert data["desired_state"] == "ENABLED"
        assert data["status"] == "STARTING"
        assert data["cloudflare_tunnel_id"] == "tun-abc"
        assert data["public_address"] == _HOSTNAME

        # Cloudflare orchestration: exactly one tunnel, loopback ingress + catch-all,
        # exactly one CNAME.
        assert client.created_names == [f"mcs-panel-{_HOSTNAME}"]
        assert len(client.ingresses) == 1
        tunnel_id, ingress = client.ingresses[0]
        assert tunnel_id == "tun-abc"
        assert {"hostname": _HOSTNAME, "service": "http://127.0.0.1:8000"} in ingress
        assert {"service": "http_status:404"} in ingress
        assert client.cnames == [(_HOSTNAME, "tun-abc")]

        # Supervisor started with the PROVISIONED tunnel token (never the API token).
        assert supervisor.starts == [_TUNNEL_TOKEN.encode("utf-8")]

        # Persisted: encrypted (bytes, != plaintext) and round-trips.
        panel = await _load_panel()
        assert panel.desired_state == DesiredState.ENABLED
        assert panel.status == ExposureStatus.STARTING
        assert panel.cloudflare_tunnel_id == "tun-abc"
        ct = panel.cloudflare_token_ciphertext
        assert isinstance(ct, bytes)
        assert ct != _TUNNEL_TOKEN.encode("utf-8")
        assert build_backup_encryption(key_path).decrypt(ct) == _TUNNEL_TOKEN.encode("utf-8")

    async def test_enable_payload_never_exposes_token(self, monkeypatch) -> None:
        client = FakeCloudflareClient()
        supervisor = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, supervisor)
        handler = SetPanelExposureHandler(event_bus=EventBus())

        result = await handler.handle(
            SetPanelExposureCommand(
                method="cloudflare_tunnel",
                desired_state="ENABLED",
                cloudflare_token=_API_TOKEN,
                hostname=_HOSTNAME,
            )
        )
        assert result.success
        assert "token" not in repr(result.data).lower()
        assert "cloudflare_token_ciphertext" not in result.data

    async def test_enable_idempotent_no_reprovision(self, monkeypatch) -> None:
        client = FakeCloudflareClient()
        supervisor = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, supervisor)
        handler = SetPanelExposureHandler(event_bus=EventBus())
        cmd = SetPanelExposureCommand(
            method="cloudflare_tunnel",
            desired_state="ENABLED",
            cloudflare_token=_API_TOKEN,
            hostname=_HOSTNAME,
        )

        await handler.handle(cmd)
        # Same method + desired_state -> early return, nothing reprovisioned.
        result = await handler.handle(cmd)
        assert result.success
        assert client.created_names == [f"mcs-panel-{_HOSTNAME}"]
        assert supervisor.starts == [_TUNNEL_TOKEN.encode("utf-8")]


class TestSetPanelExposureDisable:
    async def test_disable_stops_supervisor_and_clears_secret(self, monkeypatch) -> None:
        client = FakeCloudflareClient()
        supervisor = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, supervisor)
        handler = SetPanelExposureHandler(event_bus=EventBus())

        enable = await handler.handle(
            SetPanelExposureCommand(
                method="cloudflare_tunnel",
                desired_state="ENABLED",
                cloudflare_token=_API_TOKEN,
                hostname=_HOSTNAME,
            )
        )
        assert enable.success
        assert supervisor.is_running

        disable = await handler.handle(
            SetPanelExposureCommand(
                method="cloudflare_tunnel",
                desired_state="DISABLED",
            )
        )
        assert disable.success
        data = disable.data
        assert data["desired_state"] == "DISABLED"
        assert data["status"] == "DISABLED"
        assert data["cloudflare_tunnel_id"] is None
        assert data["public_address"] is None
        assert supervisor.stops == 1

        panel = await _load_panel()
        assert panel.desired_state == DesiredState.DISABLED
        assert panel.cloudflare_tunnel_id is None
        assert panel.cloudflare_token_ciphertext is None
        assert panel.public_address is None


class TestSetPanelExposureAuthFailure:
    async def test_auth_error_maps_to_reclaim_required(self, monkeypatch) -> None:
        client = FakeCloudflareClient(auth_error=True)
        supervisor = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, supervisor)
        handler = SetPanelExposureHandler(event_bus=EventBus())

        result = await handler.handle(
            SetPanelExposureCommand(
                method="cloudflare_tunnel",
                desired_state="ENABLED",
                cloudflare_token=_API_TOKEN,
                hostname=_HOSTNAME,
            )
        )
        assert result.success
        data = result.data
        assert data["desired_state"] == "ENABLED"
        assert data["status"] == "RECLAIM_REQUIRED"
        assert data["error_code"] == "RECLAIM_REQUIRED"
        assert data["cloudflare_tunnel_id"] is None
        assert data["public_address"] is None

        # No silent reissue: exactly one tunnel attempt, supervisor untouched.
        assert client.create_attempts == 1
        assert client.created_names == []
        assert supervisor.starts == []

        panel = await _load_panel()
        assert panel.status == ExposureStatus.RECLAIM_REQUIRED
        assert panel.error_code == "RECLAIM_REQUIRED"
        assert panel.cloudflare_tunnel_id is None
        assert panel.cloudflare_token_ciphertext is None


class TestReconcileRestartFromPersistedState:
    async def test_reconcile_starts_from_stored_ciphertext_no_new_tunnel(
        self, monkeypatch
    ) -> None:
        client = FakeCloudflareClient()
        first = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, first)
        handler = SetPanelExposureHandler(event_bus=EventBus())
        await handler.handle(
            SetPanelExposureCommand(
                method="cloudflare_tunnel",
                desired_state="ENABLED",
                cloudflare_token=_API_TOKEN,
                hostname=_HOSTNAME,
            )
        )
        assert first.starts == [_TUNNEL_TOKEN.encode("utf-8")]

        # Supervisor singleton is reset (simulates app restart): the process died,
        # the persisted encrypted creds survive. A fresh supervisor must be used.
        second = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, second)
        reconcile = ReconcileExposureHandler(event_bus=EventBus())

        result = await reconcile.handle(ReconcileExposureCommand())
        assert result.success

        # Reconcile starts cloudflared from the persisted ciphertext...
        assert second.starts == [_TUNNEL_TOKEN.encode("utf-8")]
        # ...without minting a new tunnel / new CNAME.
        assert client.created_names == [f"mcs-panel-{_HOSTNAME}"]
        assert client.cnames == [(_HOSTNAME, "tun-abc")]

    async def test_reconcile_after_disable_leaves_supervisor_stopped(
        self, monkeypatch
    ) -> None:
        client = FakeCloudflareClient()
        supervisor = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, supervisor)
        set_handler = SetPanelExposureHandler(event_bus=EventBus())
        await set_handler.handle(
            SetPanelExposureCommand(
                method="cloudflare_tunnel",
                desired_state="ENABLED",
                cloudflare_token=_API_TOKEN,
                hostname=_HOSTNAME,
            )
        )
        await set_handler.handle(
            SetPanelExposureCommand(method="cloudflare_tunnel", desired_state="DISABLED")
        )
        supervisor.starts.clear()
        supervisor.stops = 0

        reconcile = ReconcileExposureHandler(event_bus=EventBus())
        result = await reconcile.handle(ReconcileExposureCommand())
        assert result.success

        assert supervisor.starts == []
        assert supervisor.stops == 1

        panel = await _load_panel()
        assert panel.desired_state == DesiredState.DISABLED
        assert panel.status == ExposureStatus.DISABLED


class TestPanelTokenAesGcmRoundTrip:
    async def test_plaintext_encrypt_differs_decrypt_recovers(self, key_path) -> None:
        enc = build_backup_encryption(key_path)
        plaintext = _TUNNEL_TOKEN.encode("utf-8")

        ciphertext = enc.encrypt(plaintext)

        assert isinstance(ciphertext, bytes)
        assert ciphertext != plaintext
        assert enc.decrypt(ciphertext) == plaintext

    async def test_panel_payload_never_exposes_token_or_ciphertext(self, key_path) -> None:
        enc = build_backup_encryption(key_path)
        plaintext = _TUNNEL_TOKEN.encode("utf-8")
        panel = PanelExposure(
            method="cloudflare_tunnel",
            desired_state="ENABLED",
            status="ACTIVE",
            public_address=_HOSTNAME,
            cloudflare_tunnel_id="tun-abc",
            cloudflare_token_ciphertext=enc.encrypt(plaintext),
        )
        payload = _panel_payload(panel)
        assert "cloudflare_token_ciphertext" not in payload
        assert plaintext.decode("utf-8") not in repr(payload)
        assert _TUNNEL_TOKEN not in str(payload)


class TestPanelTokenReclaimRotation:
    """RECLAIM_REQUIRED recovery (Batch 7.2a Deviation 1).

    A fresh owner-supplied token while the panel is already
    cloudflare_tunnel/ENABLED but status == RECLAIM_REQUIRED must rotate the
    stored ciphertext in place and restart cloudflared — never silently
    no-op, never silently require disable→enable, never mint a new tunnel.
    """

    async def _enabled_panel(
        self, client, _supervisor, handler
    ) -> None:
        result = await handler.handle(
            SetPanelExposureCommand(
                method="cloudflare_tunnel",
                desired_state="ENABLED",
                cloudflare_token=_API_TOKEN,
                hostname=_HOSTNAME,
            )
        )
        assert result.success
        assert result.data["status"] == "STARTING"
        assert client.created_names == [f"mcs-panel-{_HOSTNAME}"]

    async def test_reclaim_rotation_happens_in_place(self, monkeypatch) -> None:
        """A: RECLAIM_REQUIRED + fresh token -> rotation happens; C: restart attempted."""
        client = FakeCloudflareClient()
        supervisor = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, supervisor)
        handler = SetPanelExposureHandler(event_bus=EventBus())
        await self._enabled_panel(client, supervisor, handler)

        await _set_panel_reclaim_required()

        result = await handler.handle(
            SetPanelExposureCommand(
                method="cloudflare_tunnel",
                desired_state="ENABLED",
                cloudflare_token=_ROTATION_TOKEN,
                hostname=_HOSTNAME,
            )
        )
        assert result.success
        data = result.data
        assert data["status"] == "STARTING"
        assert data["cloudflare_tunnel_id"] == "tun-abc"
        assert data["error_code"] is None

        # No re-provision: exactly the one original tunnel + CNAME, no duplicates.
        assert client.create_attempts == 1
        assert client.created_names == [f"mcs-panel-{_HOSTNAME}"]
        assert client.cnames == [(_HOSTNAME, "tun-abc")]

        # C: the supervised child was restarted with the replacement token
        # (restart = stop old process first, then start with the new token).
        assert supervisor.stops == 1
        assert supervisor.starts == [
            _TUNNEL_TOKEN.encode("utf-8"),
            _ROTATION_TOKEN.encode("utf-8"),
        ]

    async def test_reclaim_rotation_replaces_ciphertext(self, key_path, monkeypatch) -> None:
        """B: ciphertext changes and decrypts to the fresh token."""
        client = FakeCloudflareClient()
        supervisor = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, supervisor)
        handler = SetPanelExposureHandler(event_bus=EventBus())
        await self._enabled_panel(client, supervisor, handler)
        old_ct = (await _load_panel()).cloudflare_token_ciphertext

        await _set_panel_reclaim_required()
        await handler.handle(
            SetPanelExposureCommand(
                method="cloudflare_tunnel",
                desired_state="ENABLED",
                cloudflare_token=_ROTATION_TOKEN,
                hostname=_HOSTNAME,
            )
        )

        panel = await _load_panel()
        assert panel.cloudflare_tunnel_id == "tun-abc"
        new_ct = panel.cloudflare_token_ciphertext
        assert isinstance(new_ct, bytes)
        assert new_ct != old_ct
        assert build_backup_encryption(key_path).decrypt(new_ct) == _ROTATION_TOKEN.encode("utf-8")

    async def test_reclaim_rotation_recovers_out_of_reclaim(self, monkeypatch) -> None:
        """D: successful rotation leaves RECLAIM_REQUIRED (status STARTING,
        error cleared); the supervisor feedback loop then drives ACTIVE."""
        client = FakeCloudflareClient()
        supervisor = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, supervisor)
        handler = SetPanelExposureHandler(event_bus=EventBus())
        await self._enabled_panel(client, supervisor, handler)

        await _set_panel_reclaim_required()
        result = await handler.handle(
            SetPanelExposureCommand(
                method="cloudflare_tunnel",
                desired_state="ENABLED",
                cloudflare_token=_ROTATION_TOKEN,
                hostname=_HOSTNAME,
            )
        )
        assert result.data["status"] == "STARTING"
        assert result.data["error_code"] is None
        panel = await _load_panel()
        assert panel.status == ExposureStatus.STARTING
        assert panel.desired_state == DesiredState.ENABLED

    async def test_invalid_replacement_token_keeps_reclaim_required(
        self, monkeypatch
    ) -> None:
        """E: an invalid replacement token keeps RECLAIM_REQUIRED (via the
        supervisor auth-failure feedback — never a silent success)."""
        client = FakeCloudflareClient()
        supervisor = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, supervisor)
        handler = SetPanelExposureHandler(event_bus=EventBus())
        await self._enabled_panel(client, supervisor, handler)

        await _set_panel_reclaim_required()
        result = await handler.handle(
            SetPanelExposureCommand(
                method="cloudflare_tunnel",
                desired_state="ENABLED",
                cloudflare_token=_INVALID_ROTATION_TOKEN,
                hostname=_HOSTNAME,
            )
        )
        assert result.success
        # The command hands the token to cloudflared (session attempted)...
        assert supervisor.starts[-1] == _INVALID_ROTATION_TOKEN.encode("utf-8")

        # ...cloudflared rejects it at the edge -> the supervisor feedback loop
        # re-persists RECLAIM_REQUIRED; the tunnel id is preserved for retry.
        await _persist_panel_status(ExposureStatus.RECLAIM_REQUIRED)
        panel = await _load_panel()
        assert panel.status == ExposureStatus.RECLAIM_REQUIRED
        assert panel.error_code == "RECLAIM_REQUIRED"
        assert panel.cloudflare_tunnel_id == "tun-abc"
        # No new credential was minted; the single original tunnel remains.
        assert client.create_attempts == 1

    async def test_reclaim_rotation_repeated_request_idempotent(
        self, monkeypatch
    ) -> None:
        """F: a repeated identical rotation request is a no-op (no second
        restart, no re-encryption) once the panel left RECLAIM_REQUIRED."""
        client = FakeCloudflareClient()
        supervisor = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, supervisor)
        handler = SetPanelExposureHandler(event_bus=EventBus())
        await self._enabled_panel(client, supervisor, handler)
        await _set_panel_reclaim_required()

        rotation_cmd = SetPanelExposureCommand(
            method="cloudflare_tunnel",
            desired_state="ENABLED",
            cloudflare_token=_ROTATION_TOKEN,
            hostname=_HOSTNAME,
        )
        first = await handler.handle(rotation_cmd)
        assert first.data["status"] == "STARTING"
        starts_after_first = list(supervisor.starts)
        ct_after_first = (await _load_panel()).cloudflare_token_ciphertext

        second = await handler.handle(rotation_cmd)
        assert second.success
        assert supervisor.starts == starts_after_first
        assert (await _load_panel()).cloudflare_token_ciphertext == ct_after_first
        assert client.create_attempts == 1

    async def test_reclaim_rotation_payload_never_exposes_token(
        self, monkeypatch
    ) -> None:
        """G: the rotation result never returns/logs the plaintext token."""
        client = FakeCloudflareClient()
        supervisor = FakeSupervisor()
        _patch_boundaries(monkeypatch, client, supervisor)
        handler = SetPanelExposureHandler(event_bus=EventBus())
        await self._enabled_panel(client, supervisor, handler)
        await _set_panel_reclaim_required()

        result = await handler.handle(
            SetPanelExposureCommand(
                method="cloudflare_tunnel",
                desired_state="ENABLED",
                cloudflare_token=_ROTATION_TOKEN,
                hostname=_HOSTNAME,
            )
        )
        assert result.success
        assert "token" not in repr(result.data).lower()
        assert "cloudflare_token_ciphertext" not in result.data
        assert _ROTATION_TOKEN not in str(result.data)
