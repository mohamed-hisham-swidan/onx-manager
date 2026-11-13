from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import AppSettings
from app.core.event_bus import EventBus
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
from app.modules.shared.value_objects import ServerId
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository


def _server_mode():
    from app.modules.server.domain import value_objects

    return value_objects.ServerMode


async def _load_mode(server_id: str):
    async with database.session_factory() as session:
        server = await SQLServerRepository(session).get(ServerId(server_id))
    return server.mode


class TestCreateServerMode:
    def test_command_defaults_to_simple(self) -> None:
        cmd = CreateServerCommand(name="default-mode", minecraft_version="1.20.4")
        assert cmd.mode == "simple"

    @pytest.mark.asyncio
    async def test_handler_persists_default_simple(self, tmp_path: Path) -> None:
        handler = CreateServerHandler(EventBus())
        srv_dir = tmp_path / "srv-default-mode"
        cmd = CreateServerCommand(
            name="default-mode",
            minecraft_version="1.20.4",
            provider="local",
        )
        with (
            patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.server.application.services.jar_service.resolve_server_dir",
                return_value=str(srv_dir),
            ),
        ):
            result = await handler.handle(cmd)

        assert result.success is True
        assert await _load_mode(result.data["server_id"]) is _server_mode().SIMPLE

    @pytest.mark.asyncio
    async def test_handler_rejects_advanced_when_flag_disabled(self, tmp_path: Path) -> None:
        handler = CreateServerHandler(EventBus())
        srv_dir = tmp_path / "srv-advanced-disabled"
        cmd = CreateServerCommand(
            name="advanced-disabled",
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
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            servers = await repo.list()
            assert not any(s.name == "advanced-disabled" for s in servers)

    @pytest.mark.asyncio
    async def test_handler_persists_explicit_advanced_when_flag_enabled(
        self, tmp_path: Path
    ) -> None:
        handler = CreateServerHandler(EventBus())
        srv_dir = tmp_path / "srv-advanced-mode"
        host_state_dir = tmp_path / "host-state"
        cmd = CreateServerCommand(
            name="advanced-mode",
            minecraft_version="1.20.4",
            provider="local",
            mode="advanced",
        )
        with (
            patch(
                "app.core.config.ConfigFactory.global_settings",
                return_value=AppSettings(
                    advanced_mode_enabled=True,
                    host_state_dir=str(host_state_dir),
                    servers_data_dir=str(tmp_path / "servers"),
                ),
            ),
            patch(
                "app.modules.server.application.services.jar_service.download_server_jar",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.server.application.services.jar_service.resolve_server_dir",
                return_value=str(srv_dir),
            ),
        ):
            result = await handler.handle(cmd)

        assert result.success is True
        server_id = result.data["server_id"]
        assert await _load_mode(server_id) is _server_mode().ADVANCED

        repo_git = host_state_dir / "repos" / server_id / "repo.git"
        assert repo_git.is_dir()
        main_worktree = srv_dir / ".onx" / "worktrees" / "main"
        assert (main_worktree / "server.properties").is_file()
        assert (main_worktree / "onx-jars.lock.json").is_file()
        assert not (main_worktree / "eula.txt").exists()

        async with database.session_factory() as session:
            branch = await SQLVersioningRepository(session).get_branch_by_name(server_id, "main")
        assert branch is not None
        assert branch.is_protected is True
        assert branch.status.value == "active"


class TestImportServerMode:
    def test_command_defaults_to_simple(self) -> None:
        cmd = ImportServerCommand(
            name="default-import",
            source_path="/tmp/x",
            minecraft_version="1.20.4",
        )
        assert cmd.mode == "simple"

    @pytest.mark.asyncio
    async def test_handler_persists_default_simple(self, tmp_path: Path) -> None:
        source = tmp_path / "source-simple"
        source.mkdir()
        (source / "server.jar").write_bytes(b"PK fake")
        target = tmp_path / "imported-simple"

        handler = ImportServerHandler(EventBus())
        cmd = ImportServerCommand(
            name="imported-simple",
            source_path=str(source),
            minecraft_version="1.20.4",
            mode="simple",
        )
        with patch(
            "app.modules.server.application.commands.import_server.resolve_server_dir",
            return_value=str(target),
        ):
            result = await handler.handle(cmd)

        assert result.success is True
        assert await _load_mode(result.data["server_id"]) is _server_mode().SIMPLE

    @pytest.mark.asyncio
    async def test_handler_rejects_explicit_advanced_unconditionally(self, tmp_path: Path) -> None:
        source = tmp_path / "source-server"
        source.mkdir()
        (source / "server.jar").write_bytes(b"PK fake")
        target = tmp_path / "imported-advanced"

        handler = ImportServerHandler(EventBus())
        cmd = ImportServerCommand(
            name="imported-advanced",
            source_path=str(source),
            minecraft_version="1.20.4",
            mode="advanced",
        )
        with patch(
            "app.modules.server.application.commands.import_server.resolve_server_dir",
            return_value=str(target),
        ):
            result = await handler.handle(cmd)

        assert result.success is False
        assert result.error_code == "CONFLICT"
        assert result.error == "Advanced mode imports are not supported in this release"
        assert result.details == {"mode": "advanced"}
        assert target.exists() is False
        async with database.session_factory() as session:
            repo = SQLServerRepository(session)
            servers = await repo.list()
            assert not any(s.name == "imported-advanced" for s in servers)
