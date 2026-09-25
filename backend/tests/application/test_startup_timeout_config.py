from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import InvalidValueError
from app.core.settings_store import get_live_settings, update_settings
from app.modules.server.application.commands.update_server_config import (
    UpdateServerConfigCommand,
    UpdateServerConfigHandler,
)
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.value_objects import (
    JavaArguments,
    MemoryAllocation,
    PortNumber,
    ServerProperties,
    ServerType,
)
from app.modules.shared.value_objects import MinecraftVersion, ServerId


def test_server_aggregate_startup_timeout_validation() -> None:
    server = Server(
        server_id=ServerId(),
        name="test-server",
        server_type=ServerType.VANILLA,
        minecraft_version=MinecraftVersion(1, 21, 1),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(),
        properties=ServerProperties(port=PortNumber(25565)),
        startup_timeout_seconds=150,
    )
    assert server.startup_timeout_seconds == 150

    # Valid update
    server.update_startup_timeout(300)
    assert server.startup_timeout_seconds == 300

    # Reset to None (use global default)
    server.update_startup_timeout(None)
    assert server.startup_timeout_seconds is None

    # Below clamp (min 30)
    with pytest.raises(InvalidValueError):
        server.update_startup_timeout(29)

    # Above clamp (max 1800)
    with pytest.raises(InvalidValueError):
        server.update_startup_timeout(1801)


@pytest.mark.asyncio
async def test_update_server_config_startup_timeout() -> None:
    server_id = ServerId()
    server = Server(
        server_id=server_id,
        name="test-srv",
        server_type=ServerType.VANILLA,
        minecraft_version=MinecraftVersion(1, 21, 1),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(),
        properties=ServerProperties(port=PortNumber(25565)),
        startup_timeout_seconds=None,
    )

    event_bus = MagicMock()
    handler = UpdateServerConfigHandler(event_bus)

    with (
        patch(
            "app.modules.server.application.commands.update_server_config.SQLServerRepository"
        ) as mock_repo_cls,
        patch(
            "app.modules.server.application.commands.update_server_config.UnitOfWork"
        ) as mock_uow_cls,
    ):
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=server)
        mock_repo.save = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        mock_uow = MagicMock()
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=None)
        mock_uow.commit = AsyncMock()
        mock_uow.session = MagicMock()
        mock_uow_cls.return_value = mock_uow

        # Update with new timeout
        cmd = UpdateServerConfigCommand(
            server_id=str(server_id),
            startup_timeout_seconds=240,
            update_startup_timeout=True,
        )
        res = await handler.handle(cmd)
        assert res.success is True
        assert server.startup_timeout_seconds == 240

        # Update resetting to None
        cmd_reset = UpdateServerConfigCommand(
            server_id=str(server_id),
            startup_timeout_seconds=None,
            update_startup_timeout=True,
        )
        res_reset = await handler.handle(cmd_reset)
        assert res_reset.success is True
        assert server.startup_timeout_seconds is None


def test_live_settings_startup_timeouts() -> None:
    settings = get_live_settings()
    assert settings.server_startup_timeout_seconds == 120
    assert settings.test_boot_timeout_seconds == 120

    # Verify clamping behavior
    update_settings({"server_startup_timeout_seconds": 15})
    assert get_live_settings().server_startup_timeout_seconds == 30  # clamped to 30

    update_settings({"test_boot_timeout_seconds": 2500})
    assert get_live_settings().test_boot_timeout_seconds == 1800  # clamped to 1800

    # Restore defaults
    update_settings({
        "server_startup_timeout_seconds": 120,
        "test_boot_timeout_seconds": 120,
    })
    assert get_live_settings().server_startup_timeout_seconds == 120
    assert get_live_settings().test_boot_timeout_seconds == 120
