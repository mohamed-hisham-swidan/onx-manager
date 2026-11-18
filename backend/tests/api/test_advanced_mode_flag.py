"""Tests for advanced_mode_enabled configuration flag and D-10 import gate.

P2-1 Core Substrate — B4f
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.api.errors import check_command_result
from app.api.v1.routers.setup import (
    UpdateAccessModeRequest,
    get_setup_status,
    update_access_mode,
)
from app.core.command_bus import CommandResult
from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.exceptions import MCSError
from app.core.persistence.db import database
from app.modules.server.application.commands.create_server import (
    CreateServerCommand,
    CreateServerHandler,
)
from app.modules.server.application.commands.import_server import (
    ImportServerCommand,
    ImportServerHandler,
)
from app.modules.server.infrastructure.repository import SQLServerRepository


class TestAdvancedModeConfig:
    def test_default_flag_is_true_on_posix_and_false_on_non_posix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONX_ADVANCED_MODE_ENABLED", raising=False)
        monkeypatch.delenv("MCS_ADVANCED_MODE_ENABLED", raising=False)
        from app.core.config import ConfigFactory

        monkeypatch.setattr(os, "name", "posix")
        assert AppSettings().advanced_mode_enabled is True
        assert ConfigFactory.global_settings().advanced_mode_enabled is True

        monkeypatch.setattr(os, "name", "nt")
        assert AppSettings().advanced_mode_enabled is False
        assert ConfigFactory.global_settings().advanced_mode_enabled is False

    def test_onx_env_var_parsing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # ONX_ADVANCED_MODE_ENABLED=false overrides the POSIX True default
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.setenv("ONX_ADVANCED_MODE_ENABLED", "false")
        assert AppSettings().advanced_mode_enabled is False

        # ONX_ADVANCED_MODE_ENABLED=true overrides the non-POSIX False default
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setenv("ONX_ADVANCED_MODE_ENABLED", "true")
        assert AppSettings().advanced_mode_enabled is True

        monkeypatch.delenv("ONX_ADVANCED_MODE_ENABLED", raising=False)
        monkeypatch.setattr(os, "name", "posix")
        monkeypatch.setenv("ONX_ADVANCED_MODE_ENABLED", "true")
        assert AppSettings().advanced_mode_enabled is True

        monkeypatch.setenv("ONX_ADVANCED_MODE_ENABLED", "1")
        assert AppSettings().advanced_mode_enabled is True

        monkeypatch.setenv("ONX_ADVANCED_MODE_ENABLED", "false")
        assert AppSettings().advanced_mode_enabled is False

        monkeypatch.setenv("ONX_ADVANCED_MODE_ENABLED", "0")
        assert AppSettings().advanced_mode_enabled is False

    def test_mcs_env_var_parsing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCS_ADVANCED_MODE_ENABLED", "true")
        assert AppSettings().advanced_mode_enabled is True

        monkeypatch.setenv("MCS_ADVANCED_MODE_ENABLED", "false")
        assert AppSettings().advanced_mode_enabled is False


class TestSetupRoutesAdvancedModeMerge:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("flag_value", [False, True])
    async def test_get_setup_status_merges_live_flag(self, flag_value: bool) -> None:
        fake_bus = AsyncMock()
        # Bus payload deliberately omits advanced_mode_enabled
        fake_bus.ask.return_value = {
            "initialized": True,
            "access_mode": "LOCAL",
            "user_count": 1,
            "version": "1.0.0",
        }

        with patch(
            "app.core.config.ConfigFactory.global_settings",
            return_value=AppSettings(advanced_mode_enabled=flag_value),
        ):
            resp = await get_setup_status(query_bus=fake_bus)

        assert resp.initialized is True
        assert resp.access_mode == "LOCAL"
        assert resp.advanced_mode_enabled is flag_value

    @pytest.mark.asyncio
    @pytest.mark.parametrize("flag_value", [False, True])
    async def test_get_setup_status_overwrites_stale_payload_flag(self, flag_value: bool) -> None:
        fake_bus = AsyncMock()
        # Bus payload contains opposite value; live setting must win
        fake_bus.ask.return_value = {
            "initialized": True,
            "access_mode": "LOCAL",
            "user_count": 1,
            "version": "1.0.0",
            "advanced_mode_enabled": not flag_value,
        }

        with patch(
            "app.core.config.ConfigFactory.global_settings",
            return_value=AppSettings(advanced_mode_enabled=flag_value),
        ):
            resp = await get_setup_status(query_bus=fake_bus)

        assert resp.advanced_mode_enabled is flag_value

    @pytest.mark.asyncio
    @pytest.mark.parametrize("flag_value", [False, True])
    async def test_update_access_mode_merges_live_flag(self, flag_value: bool) -> None:
        fake_bus = AsyncMock()
        # Bus payload deliberately omits advanced_mode_enabled
        fake_bus.send.return_value = CommandResult(
            success=True,
            data={
                "initialized": True,
                "access_mode": "GLOBAL",
                "user_count": 1,
                "version": "1.0.0",
            },
        )
        owner_user: dict[str, Any] = {"roles": ["owner"], "permissions": ["*"]}
        req = UpdateAccessModeRequest(access_mode="GLOBAL")

        with patch(
            "app.core.config.ConfigFactory.global_settings",
            return_value=AppSettings(advanced_mode_enabled=flag_value),
        ):
            resp = await update_access_mode(
                body=req,
                current_user=owner_user,
                command_bus=fake_bus,
            )

        assert resp.access_mode == "GLOBAL"
        assert resp.advanced_mode_enabled is flag_value

    @pytest.mark.asyncio
    @pytest.mark.parametrize("flag_value", [False, True])
    async def test_update_access_mode_overwrites_stale_payload_flag(self, flag_value: bool) -> None:
        fake_bus = AsyncMock()
        # Bus payload contains opposite value; live setting must win
        fake_bus.send.return_value = CommandResult(
            success=True,
            data={
                "initialized": True,
                "access_mode": "GLOBAL",
                "user_count": 1,
                "version": "1.0.0",
                "advanced_mode_enabled": not flag_value,
            },
        )
        owner_user: dict[str, Any] = {"roles": ["owner"], "permissions": ["*"]}
        req = UpdateAccessModeRequest(access_mode="GLOBAL")

        with patch(
            "app.core.config.ConfigFactory.global_settings",
            return_value=AppSettings(advanced_mode_enabled=flag_value),
        ):
            resp = await update_access_mode(
                body=req,
                current_user=owner_user,
                command_bus=fake_bus,
            )

        assert resp.access_mode == "GLOBAL"
        assert resp.advanced_mode_enabled is flag_value

    @pytest.mark.asyncio
    async def test_get_setup_status_reports_platform_default_without_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONX_ADVANCED_MODE_ENABLED", raising=False)
        monkeypatch.delenv("MCS_ADVANCED_MODE_ENABLED", raising=False)
        fake_bus = AsyncMock()
        fake_bus.ask.return_value = {
            "initialized": True,
            "access_mode": "LOCAL",
            "user_count": 1,
            "version": "1.0.0",
        }

        monkeypatch.setattr(os, "name", "posix")
        resp = await get_setup_status(query_bus=fake_bus)
        assert resp.advanced_mode_enabled is True

        monkeypatch.setattr(os, "name", "nt")
        resp = await get_setup_status(query_bus=fake_bus)
        assert resp.advanced_mode_enabled is False


class TestServerCreationGating:
    @pytest.mark.asyncio
    async def test_create_advanced_when_flag_false_raises_422(
        self, tmp_path: Path
    ) -> None:
        handler = CreateServerHandler(EventBus())
        srv_dir = tmp_path / "srv-adv-fail"
        cmd = CreateServerCommand(
            name="adv-fail",
            minecraft_version="1.20.4",
            provider="local",
            mode="advanced",
        )

        with (
            patch(
                "app.core.config.ConfigFactory.global_settings",
                return_value=AppSettings(advanced_mode_enabled=False),
            ),
            patch(
                "app.modules.server.application.services.jar_service.resolve_server_dir",
                return_value=str(srv_dir),
            ),
        ):
            result = await handler.handle(cmd)

        assert result.success is False
        assert result.error_code == "VALIDATION_ERROR"
        assert result.error == "Advanced mode is not enabled on this instance"
        assert srv_dir.exists() is False

        with pytest.raises(MCSError) as exc_info:
            check_command_result(result)
        assert exc_info.value.http_status == 422
        assert exc_info.value.code == "VALIDATION_ERROR"

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            servers = await repo.list()
            assert not any(s.name == "adv-fail" for s in servers)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("flag_value", [False, True])
    async def test_import_advanced_unconditional_raises_409(
        self, tmp_path: Path, flag_value: bool
    ) -> None:
        source = tmp_path / "source-adv"
        source.mkdir()
        (source / "server.jar").write_bytes(b"PK fake")
        target = tmp_path / "imported-adv"

        handler = ImportServerHandler(EventBus())
        cmd = ImportServerCommand(
            name="imp-adv",
            source_path=str(source),
            minecraft_version="1.20.4",
            mode="advanced",
        )

        with (
            patch(
                "app.core.config.ConfigFactory.global_settings",
                return_value=AppSettings(advanced_mode_enabled=flag_value),
            ),
            patch(
                "app.modules.server.application.commands.import_server.resolve_server_dir",
                return_value=str(target),
            ),
        ):
            result = await handler.handle(cmd)

        assert result.success is False
        assert result.error_code == "CONFLICT"
        assert result.error == "Advanced mode imports are not supported in this release"
        assert result.details == {"mode": "advanced"}
        assert target.exists() is False

        with pytest.raises(MCSError) as exc_info:
            check_command_result(result)
        assert exc_info.value.http_status == 409
        assert exc_info.value.code == "CONFLICT"

        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            servers = await repo.list()
            assert not any(s.name == "imp-adv" for s in servers)

    @pytest.mark.asyncio
    async def test_simple_mode_create_and_import_not_gated_by_flag(
        self, tmp_path: Path
    ) -> None:
        # Flag is explicitly False, simple mode must succeed for both create and import
        create_handler = CreateServerHandler(EventBus())
        create_dir = tmp_path / "srv-simple-create"
        create_cmd = CreateServerCommand(
            name="simple-create",
            minecraft_version="1.20.4",
            provider="local",
            mode="simple",
        )

        with (
            patch(
                "app.core.config.ConfigFactory.global_settings",
                return_value=AppSettings(advanced_mode_enabled=False),
            ),
            patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.server.application.services.jar_service.resolve_server_dir",
                return_value=str(create_dir),
            ),
        ):
            create_res = await create_handler.handle(create_cmd)

        assert create_res.success is True
        data = check_command_result(create_res)
        assert "server_id" in data

        source = tmp_path / "source-simple"
        source.mkdir()
        (source / "server.jar").write_bytes(b"PK fake")
        import_target = tmp_path / "imported-simple"

        import_handler = ImportServerHandler(EventBus())
        import_cmd = ImportServerCommand(
            name="simple-import",
            source_path=str(source),
            minecraft_version="1.20.4",
            mode="simple",
        )

        with (
            patch(
                "app.core.config.ConfigFactory.global_settings",
                return_value=AppSettings(advanced_mode_enabled=False),
            ),
            patch(
                "app.modules.server.application.commands.import_server.resolve_server_dir",
                return_value=str(import_target),
            ),
        ):
            import_res = await import_handler.handle(import_cmd)

        assert import_res.success is True
        import_data = check_command_result(import_res)
        assert "server_id" in import_data
