"""Application-layer tests for Panel Playit HTTP and UPnP Port Forwarding commands (Batch 7.2b)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.modules.auth.infrastructure.models  # noqa: F401
import app.modules.exposure.infrastructure.models  # noqa: F401
import app.modules.server.infrastructure.models  # noqa: F401
from app.core.config import init_active_panel_bind
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.settings_store import get_live_settings, init_settings_store
from app.modules.auth.domain.aggregate import AccessMode
from app.modules.auth.infrastructure.repository import SQLSystemStateRepository
from app.modules.exposure.application.commands import (
    SetPanelExposureCommand,
    SetPanelExposureHandler,
)
from app.modules.exposure.domain.aggregate import HostPlayitAgent, PanelExposure
from app.modules.exposure.domain.value_objects import (
    DesiredState,
    ExposureStatus,
    PanelExposureMethod,
)
from app.modules.exposure.infrastructure.playit_api import (
    PlayitRundataDto,
    PlayitTunnelDto,
)
from app.modules.exposure.infrastructure.repository import (
    SQLHostAgentRepository,
    SQLPanelExposureRepository,
)
from app.modules.exposure.infrastructure.upnp import UPnPResult
from app.modules.storage.encryption import build_backup_encryption

pytestmark = pytest.mark.asyncio


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

    yield

    await engine.dispose()


class TestPlayitHttpPanelExposure:
    async def test_enable_playit_http_when_claimed(self, tmp_path) -> None:
        key_file = tmp_path / "enc.key"
        enc = build_backup_encryption(str(key_file))
        ciphertext = enc.encrypt(b"existing-playit-secret")

        async with UnitOfWork() as uow:
            agent_repo = SQLHostAgentRepository(uow.session)
            agent = HostPlayitAgent(id="default", secret_ciphertext=ciphertext)
            await agent_repo.save(agent)
            repo = SQLPanelExposureRepository(uow.session)
            panel = PanelExposure(
                id="default",
                method=PanelExposureMethod.NONE,
                desired_state=DesiredState.DISABLED,
                playit_tunnel_id="tunnel-existing-123",
            )
            await repo.save(panel)
            await uow.commit()

        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="playit_http",
            desired_state="ENABLED",
        )

        sup = AsyncMock()
        sup.is_running = True
        sup.status = ExposureStatus.ACTIVE
        sup.claim_url = None
        sup.claim_code = None

        mock_rundata = PlayitRundataDto(
            agent_id="default",
            agent_type="self-managed",
            account_status="ready",
            tunnels=[
                PlayitTunnelDto(
                    id="tunnel-existing-123",
                    name="onx-panel-default",
                    display_address="test-panel.at.ply.gg:8000",
                    port_type="tcp",
                    local_ip="127.0.0.1",
                    local_port=8000,
                )
            ],
        )

        with (
            patch(
                "app.modules.exposure.application.commands._panel_encryption",
                return_value=enc,
            ),
            patch(
                "app.modules.exposure.application.commands.get_playit_supervisor",
                return_value=sup,
            ),
            patch(
                "app.modules.exposure.infrastructure.playit_api.PlayitApiClient.get_rundata",
                AsyncMock(return_value=mock_rundata),
            ),
        ):
            result = await handler.handle(cmd)
            assert result.success is True
            data = result.data
            assert data["method"] == "playit_http"
            assert data["desired_state"] == "ENABLED"
            assert data["status"] == "ACTIVE"
            assert data["playit_tunnel_id"] == "tunnel-existing-123"
            assert data["protocol"] == "http"
            sup.start.assert_awaited_once()
            assert sup.start.await_args[0][0] == b"existing-playit-secret"

    async def test_enable_playit_http_when_unclaimed(self) -> None:
        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="playit_http",
            desired_state="ENABLED",
        )

        sup = AsyncMock()
        sup.is_running = True
        sup.status = ExposureStatus.CLAIM_REQUIRED
        sup.claim_url = "https://playit.gg/claim/abc123"
        sup.claim_code = "abc123"

        with patch(
            "app.modules.exposure.application.commands.get_playit_supervisor",
            return_value=sup,
        ):
            result = await handler.handle(cmd)
            assert result.success is True
            data = result.data
            assert data["method"] == "playit_http"
            assert data["desired_state"] == "ENABLED"
            assert data["status"] == "CLAIM_REQUIRED"
            sup.start.assert_awaited_once()
            assert sup.start.await_args[0][0] is None

    async def test_disable_playit_http(self) -> None:
        async with UnitOfWork() as uow:
            repo = SQLPanelExposureRepository(uow.session)
            panel = PanelExposure(
                id="default",
                method=PanelExposureMethod.PLAYIT_HTTP,
                desired_state=DesiredState.ENABLED,
                status=ExposureStatus.ACTIVE,
                public_address="https://panel.playit.gg",
            )
            await repo.save(panel)
            await uow.commit()

        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="playit_http",
            desired_state="DISABLED",
        )

        sup = AsyncMock()
        sup.is_running = False

        with patch(
            "app.modules.exposure.application.commands.get_playit_supervisor",
            return_value=sup,
        ):
            result = await handler.handle(cmd)
            assert result.success is True
            assert result.data["desired_state"] == "DISABLED"
            assert result.data["status"] == "DISABLED"
            assert result.data["public_address"] is None


class TestPortForwardPanelExposure:
    async def test_enable_port_forward_bind_mismatch_on_loopback(self) -> None:
        init_active_panel_bind("127.0.0.1", 8000)
        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="port_forward",
            desired_state="ENABLED",
            external_port=8080,
        )

        result = await handler.handle(cmd)
        assert result.success is True
        data = result.data
        assert data["method"] == "port_forward"
        assert data["desired_state"] == "ENABLED"
        assert data["status"] == "ERROR"
        assert data["error_code"] == "BIND_MISMATCH"
        assert data["auto_fixed"] is True
        assert "bound to loopback" in data["error_message"]
        assert "0.0.0.0" in data["fix_hint"]
        assert "config/settings.yaml" in data["fix_hint"]
        assert data["public_address"] is None
        assert get_live_settings().panel_bind_host == "0.0.0.0"

    async def test_enable_port_forward_subsequent_activation_after_auto_fix(self) -> None:
        init_active_panel_bind("127.0.0.1", 8000)
        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="port_forward",
            desired_state="ENABLED",
            external_port=8080,
        )

        # Run 1: Loopback triggers auto-fix, writing 0.0.0.0 to settings.yaml
        res1 = await handler.handle(cmd)
        assert res1.data["status"] == "ERROR"
        assert res1.data["error_code"] == "BIND_MISMATCH"
        assert res1.data["auto_fixed"] is True
        assert get_live_settings().panel_bind_host == "0.0.0.0"

        # Run 2 (SAME un-restarted process): Active socket bind remains 127.0.0.1.
        # Must STILL report BIND_MISMATCH (regression test for F-72B-06 false-ACTIVE bug).
        res2 = await handler.handle(cmd)
        assert res2.success is True
        assert res2.data["status"] == "ERROR"
        assert res2.data["error_code"] == "BIND_MISMATCH"
        assert res2.data["auto_fixed"] is True
        assert res2.data["public_address"] is None

    async def test_enable_port_forward_activation_after_process_restart(self) -> None:
        # Simulate post-restart environment: Uvicorn rebooted bound to 0.0.0.0:8000
        init_active_panel_bind("0.0.0.0", 8000)
        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="port_forward",
            desired_state="ENABLED",
            external_port=8080,
        )

        mock_result = UPnPResult(
            success=True,
            external_ip="93.184.216.34",
            external_port=8080,
            internal_port=8000,
        )
        with patch(
            "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
            return_value=mock_result,
        ):
            res = await handler.handle(cmd)
            assert res.success is True
            assert res.data["status"] == "ACTIVE"
            assert res.data["public_address"] == "http://93.184.216.34:8080"
            assert res.data["auto_fixed"] is False
            assert res.data["error_code"] is None

    async def test_enable_port_forward_success_on_non_loopback(self) -> None:
        init_active_panel_bind("0.0.0.0", 8000)
        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="port_forward",
            desired_state="ENABLED",
            external_port=8080,
        )

        mock_result = UPnPResult(
            success=True,
            external_ip="93.184.216.34",
            external_port=8080,
            internal_port=8000,
        )

        with patch(
            "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
            return_value=mock_result,
        ):
            result = await handler.handle(cmd)
            assert result.success is True
            data = result.data
            assert data["method"] == "port_forward"
            assert data["desired_state"] == "ENABLED"
            assert data["status"] == "ACTIVE"
            assert data["public_address"] == "http://93.184.216.34:8080"
            assert data["tls"] is False
            assert data["protocol"] == "http"
            assert data["external_port"] == 8080
            assert data["upnp_last_result"] == "SUCCEEDED"
            assert data["error_code"] is None

    async def test_enable_port_forward_security_advisory_local_mode(self) -> None:
        init_active_panel_bind("0.0.0.0", 8000)
        async with UnitOfWork() as uow:
            state_repo = SQLSystemStateRepository(uow.session)
            state = await state_repo.get()
            state.set_access_mode(AccessMode.LOCAL)
            await state_repo.save(state)
            await uow.commit()

        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="port_forward",
            desired_state="ENABLED",
            external_port=8080,
        )

        mock_result = UPnPResult(
            success=True,
            external_ip="93.184.216.34",
            external_port=8080,
            internal_port=8000,
        )

        with patch(
            "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
            return_value=mock_result,
        ):
            result = await handler.handle(cmd)
            assert result.success is True
            data = result.data
            assert "Access Mode is LOCAL" in data["security_advisory"]
            assert "Open self-registration" in data["security_advisory"]

    async def test_enable_port_forward_security_advisory_global_mode(self) -> None:
        init_active_panel_bind("0.0.0.0", 8000)
        async with UnitOfWork() as uow:
            state_repo = SQLSystemStateRepository(uow.session)
            state = await state_repo.get()
            state.set_access_mode(AccessMode.GLOBAL)
            await state_repo.save(state)
            await uow.commit()

        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="port_forward",
            desired_state="ENABLED",
            external_port=8080,
        )

        mock_result = UPnPResult(
            success=True,
            external_ip="93.184.216.34",
            external_port=8080,
            internal_port=8000,
        )

        with patch(
            "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
            return_value=mock_result,
        ):
            result = await handler.handle(cmd)
            assert result.success is True
            data = result.data
            assert "unencrypted HTTP" in data["security_advisory"]
            assert "Open self-registration" not in data["security_advisory"]

    async def test_enable_port_forward_deny_list_rejection(self) -> None:
        init_active_panel_bind("0.0.0.0", 8000)
        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="port_forward",
            desired_state="ENABLED",
            external_port=25575,  # RCON port in deny-list
        )

        result = await handler.handle(cmd)
        assert result.success is True
        data = result.data
        assert data["status"] == "ERROR"
        assert data["error_code"] == "DENY_LIST_VIOLATION"
        assert "reserved for internal services" in (data["error_message"] or "")

    async def test_enable_port_forward_upnp_unsupported(self) -> None:
        init_active_panel_bind("0.0.0.0", 8000)
        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="port_forward",
            desired_state="ENABLED",
            external_port=8000,
        )

        mock_result = UPnPResult(
            success=False,
            error_code="UPNP_UNSUPPORTED",
            error_message="UPnP is disabled on router.",
        )

        with patch(
            "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
            return_value=mock_result,
        ):
            result = await handler.handle(cmd)
            assert result.success is True
            data = result.data
            assert data["status"] == "ERROR"
            assert data["error_code"] == "UPNP_UNSUPPORTED"
            assert data["public_address"] is None

    async def test_enable_port_forward_double_nat(self) -> None:
        init_active_panel_bind("0.0.0.0", 8000)
        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="port_forward",
            desired_state="ENABLED",
            external_port=8000,
        )

        mock_result = UPnPResult(
            success=False,
            error_code="DOUBLE_NAT_DETECTED",
            error_message="Double NAT detected.",
        )

        with patch(
            "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
            return_value=mock_result,
        ):
            result = await handler.handle(cmd)
            assert result.success is True
            data = result.data
            assert data["status"] == "ERROR"
            assert data["error_code"] == "DOUBLE_NAT_DETECTED"

    async def test_disable_port_forward(self) -> None:
        async with UnitOfWork() as uow:
            repo = SQLPanelExposureRepository(uow.session)
            panel = PanelExposure(
                id="default",
                method=PanelExposureMethod.PORT_FORWARD,
                desired_state=DesiredState.ENABLED,
                status=ExposureStatus.ACTIVE,
                public_address="http://93.184.216.34:8080",
                external_port=8080,
            )
            await repo.save(panel)
            await uow.commit()

        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="port_forward",
            desired_state="DISABLED",
        )

        with patch(
            "app.modules.exposure.application.commands.AsyncUPnPService.delete_mapping",
            return_value=True,
        ) as mock_del:
            result = await handler.handle(cmd)
            assert result.success is True
            assert result.data["desired_state"] == "DISABLED"
            assert result.data["status"] == "DISABLED"
            assert result.data["public_address"] is None
            mock_del.assert_awaited_once_with(8080)

    async def test_enable_port_forward_cgnat_detected_with_fix_hint(self) -> None:
        init_active_panel_bind("0.0.0.0", 8000)
        handler = SetPanelExposureHandler(EventBus())
        cmd = SetPanelExposureCommand(
            method="port_forward",
            desired_state="ENABLED",
            external_port=8000,
        )

        mock_result = UPnPResult(
            success=False,
            external_ip="100.64.10.2",
            error_code="CGNAT_DETECTED",
            error_message="ISP CGNAT detected on WAN IP 100.64.10.2.",
        )

        with patch(
            "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
            return_value=mock_result,
        ):
            result = await handler.handle(cmd)
            assert result.success is True
            data = result.data
            assert data["status"] == "ERROR"
            assert data["error_code"] == "CGNAT_DETECTED"
            assert "Cloudflare" in (data["fix_hint"] or "")

    async def test_bind_mismatch_clears_automatically_on_startup_reconcile(self) -> None:
        from app.modules.exposure.application.commands import reconcile_panel_exposure_on_startup
        from app.modules.exposure.application.queries import (
            GetPanelExposureHandler,
            GetPanelExposureQuery,
        )

        # Step 1: Loopback 127.0.0.1 -> BIND_MISMATCH + settings updated to 0.0.0.0
        init_active_panel_bind("127.0.0.1", 8000)
        bus = EventBus()
        handler = SetPanelExposureHandler(bus)
        first = await handler.handle(
            SetPanelExposureCommand(
                method="port_forward",
                desired_state="ENABLED",
                external_port=8080,
            )
        )
        assert first.data["error_code"] == "BIND_MISMATCH"
        assert get_live_settings().panel_bind_host == "0.0.0.0"

        # Step 2: Simulate restart bound to 0.0.0.0 -> startup reconcile clears mismatch
        init_active_panel_bind("0.0.0.0", 8000)
        mock_ok = UPnPResult(
            success=True,
            external_ip="203.0.113.42",
            external_port=8080,
            internal_port=8000,
        )
        with patch(
            "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
            return_value=mock_ok,
        ):
            await reconcile_panel_exposure_on_startup(bus)
            after = await GetPanelExposureHandler().handle(GetPanelExposureQuery())
            assert after["status"] == "ACTIVE"
            assert after["error_code"] is None
            assert after["public_address"] == "http://203.0.113.42:8080"

    async def test_switching_from_port_forward_to_none_restores_loopback_and_deletes_mapping(
        self,
    ) -> None:
        from app.core.settings_store import update_settings as update_settings_store

        init_active_panel_bind("0.0.0.0", 8000)
        update_settings_store({"panel_bind_host": "0.0.0.0"})
        async with UnitOfWork() as uow:
            repo = SQLPanelExposureRepository(uow.session)
            panel = PanelExposure(
                id="default",
                method=PanelExposureMethod.PORT_FORWARD,
                desired_state=DesiredState.ENABLED,
                status=ExposureStatus.ACTIVE,
                public_address="http://203.0.113.42:8080",
                external_port=8080,
            )
            await repo.save(panel)
            await uow.commit()

        handler = SetPanelExposureHandler(EventBus())
        with patch(
            "app.modules.exposure.application.commands.AsyncUPnPService.delete_mapping",
            return_value=True,
        ) as mock_del:
            res = await handler.handle(
                SetPanelExposureCommand(method="none", desired_state="DISABLED")
            )
            assert res.data["method"] == "none"
            assert res.data["status"] == "DISABLED"
            mock_del.assert_awaited_once_with(8080)
            assert get_live_settings().panel_bind_host == "127.0.0.1"
